"""Prompt template for the policy application passes.

Phase 4 runs policy application twice per component:

1. **Top-level policy application** — decides which of the
   project-wide top-level ``policy_*`` nodes apply to a given
   component, given the component's techspec + pubapi +
   subresponsibilities. Emits ``policy_application`` edges
   from applicable policies to the component.
2. **Component-local policy application** — same shape but
   scoped to the subcomponents of a specific owning component
   with a candidate set of the component-local policies that
   component just minted. Run once per subcomponent.

Both passes use the same prompt shape:

    <policy-applications>
      <applies policy="policy_xxx11111">
        <rationale>…why it applies…</rationale>
      </applies>
      <does-not-apply policy="policy_yyy22222">
        <rationale>…why it does not apply…</rationale>
      </does-not-apply>
    </policy-applications>

The validator (``validate_policy_applications``) enforces:
- Every candidate policy is covered exactly once (applies OR
  does-not-apply, not both, not neither)
- Every policy ID is in the known candidate set
- Both arms require a non-empty rationale

The rationale is captured in handler logs only — per the stage
9 design decision it is NOT stored structurally in the DB.
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are a senior software architect deciding, for each \
candidate policy, whether it applies to a given target.

You will be given:

1. The target's metadata — a component or subcomponent, with \
its technical specification, public API surface, and the list \
of responsibilities it owns.
2. A candidate policy list — each policy carries a trigger \
phrase, a required responsibility ID, and a rationale.

For each candidate policy, you must decide: does this \
target's work activate the policy's trigger? If yes, the \
policy applies and the target must fulfill the policy's \
required responsibility (typically via a dependency edge to \
whichever component owns that responsibility). If no, the \
target's work does not activate the trigger and the policy \
does not apply.

# Output format

Emit a single ``<policy-applications>`` block containing one \
entry per candidate policy — either ``<applies \
policy="...">`` or ``<does-not-apply policy="...">`` with a \
``<rationale>`` child in both cases.

    <policy-applications>
      <applies policy="policy_tel00001">
        <rationale>This component makes LLM calls via its \
subresponsibility resp_gen_draft01, so the trigger "any LLM \
call" matches every site that resp fires from. The policy's \
required responsibility (telemetry sink) must be reachable.</rationale>
      </applies>
      <does-not-apply policy="policy_audit0001">
        <rationale>This component does not perform domain \
writes — it only reads from the projection tables. The trigger \
"any domain write" never fires here, so the audit policy does \
not apply.</rationale>
      </does-not-apply>
    </policy-applications>

# Rules

* Every candidate policy in the input list must appear exactly \
once in the output — either as ``<applies>`` or \
``<does-not-apply>``. Missing or duplicate entries are a parse \
error.
* Each entry's ``policy`` attribute must be one of the \
candidate policy IDs, verbatim.
* ``<rationale>`` is **required** in both the applies and \
does-not-apply cases. It is a non-empty paragraph explaining \
your reasoning. The rationale is the primary signal the \
reviewer uses to sanity-check the decision, so be specific \
about which parts of the target's responsibilities or public \
surface you considered.
* Do not emit any tags other than ``<applies>``, \
``<does-not-apply>``, and ``<rationale>``.
* Do not include meta-commentary outside the \
``<policy-applications>`` block.
* Err toward "applies" for edge cases. A false positive \
produces a spurious but harmless ``policy_application`` edge; \
a false negative produces a silent invariant violation that \
only surfaces in production. Applying a policy that turns out \
to be irrelevant is cheap to correct on review; missing one is \
not.
"""


def render_user_prompt(
    *,
    target_summary: str,
    target_techspec: str,
    target_pubapi: str,
    target_responsibilities_summary: str,
    candidate_policies_summary: str,
    scope: str,
    parse_error: str | None = None,
    vocab_summary: str = "",
) -> str:
    """Build the user prompt for a policy application pass.

    ``target_summary`` is a short header naming the target
    (component name + id). ``target_techspec`` / ``target_pubapi``
    are the fragment contents. ``target_responsibilities_summary``
    is the list of top-level + sub resps the target owns.
    ``candidate_policies_summary`` is the list of candidate
    policies with their full trigger + required + rationale
    content (the LLM needs the trigger phrase to make the
    decision).

    ``scope`` is either ``"top-level"`` (project-wide policies
    applied to a top-level component) or ``"component-local"``
    (component-local policies applied to one of that component's
    subcomponents). The scope only affects the header text —
    the decision task is the same either way.
    """
    parts: list[str] = []
    if vocab_summary and vocab_summary.strip():
        parts.append(vocab_summary.strip())
        parts.append("")
    parts.append(f"# Target ({scope})")
    parts.append("")
    parts.append(target_summary.strip())
    parts.append("")

    if target_techspec.strip():
        parts.append("## Technical specification")
        parts.append("")
        parts.append(target_techspec.strip())
        parts.append("")

    if target_pubapi.strip():
        parts.append("## Public surface")
        parts.append("")
        parts.append(target_pubapi.strip())
        parts.append("")

    parts.append("## Responsibilities owned by this target")
    parts.append("")
    parts.append(
        target_responsibilities_summary.strip()
        or "(no responsibilities assigned — unusual; flag for review)"
    )
    parts.append("")

    parts.append("# Candidate policies to apply")
    parts.append("")
    parts.append(
        candidate_policies_summary.strip()
        or "(no candidate policies — emit an empty <policy-applications/> block)"
    )
    parts.append("")

    if parse_error:
        parts.append("# Previous output failed structural validation")
        parts.append("")
        parts.append(
            "Your previous response did not parse into a valid "
            "<policy-applications> block. The specific error was:"
        )
        parts.append("")
        parts.append(f"> {parse_error.strip()}")
        parts.append("")
        parts.append(
            "Fix the structure and re-emit the full "
            "<policy-applications> block covering every candidate "
            "policy exactly once."
        )
        parts.append("")

    parts.append("# Task")
    parts.append("")
    parts.append(
        "For each candidate policy above, emit either "
        "<applies policy='...'> or <does-not-apply policy='...'> "
        "inside a single <policy-applications> block, with a "
        "<rationale> child in both cases. Output only the "
        "<policy-applications> block."
    )

    return "\n".join(parts).rstrip() + "\n"


def format_candidate_policies(policies: list[dict]) -> str:
    """Render a list of policy dicts as the prompt context block.

    Each dict must carry ``id``, ``name``, ``trigger``,
    ``required``, ``rationale``. These come from re-parsing each
    policy node's inline ``<policy>`` content via
    :func:`backend.graph.parsers.validators.validate_policy_blob`.
    """
    if not policies:
        return ""
    parts: list[str] = []
    for p in policies:
        pid = p.get("id", "").strip() or "(unknown-id)"
        name = p.get("name", "").strip() or "(unnamed)"
        trigger = p.get("trigger", "").strip() or "(no trigger)"
        required = p.get("required", "").strip() or "(no required resp)"
        rationale = p.get("rationale", "").strip() or "(no rationale)"
        parts.append(
            f"## `{pid}` **{name}**\n"
            f"- *trigger*: {trigger}\n"
            f"- *required*: `{required}`\n"
            f"- *rationale*: {rationale}"
        )
    return "\n\n".join(parts)
