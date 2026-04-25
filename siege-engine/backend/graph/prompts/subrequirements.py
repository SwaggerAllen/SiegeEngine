"""Prompt template for the subrequirements (``subreqs_*``) draft.

A subreqs node is the per-component analogue of the reqs_* doc.
It takes a single component's sysarch entry (role + api-intent)
and its assigned top-level responsibilities and produces the
list of subresponsibilities that the component's comparch pass
(Phase 4) will later map onto subcomponents.

Output format:

    <subrequirements>
      <subresponsibility>
        <name>Card Tokenization</name>
        <intent>…paragraph-length description…</intent>
        <derived-from>
          <resp id="resp_payment01"/>
          <resp id="resp_invoice02"/>
        </derived-from>
      </subresponsibility>
      …
    </subrequirements>

Parallel shape to ``<requirements>`` but with ``<derived-from>``
replacing ``<covers>``: each subresp lists which top-level resps
(assigned to this component) it decomposes. Many-to-many
relationship; subresps can serve multiple parent resps.

The validator enforces that every resp ID in ``<derived-from>``
is one of the top-level resps assigned to *this* component —
cross-component leaks are parse errors. It also enforces the
coverage invariant: every parent resp must appear in at least
one subresp's ``<derived-from>``.

See ``docs/architecture/v2-rearchitecture.md`` §Subrequirements
decomposition and ``docs/architecture/v2-roadmap.md`` Phase 3.
"""

from __future__ import annotations

from backend.graph.prompts._prior_framing import render_prior_review_section

_SYSTEM_PROMPT_TEMPLATE = """\
You are expanding a single component's top-level \
responsibilities into finer-grained **subresponsibilities**, \
bounded to this component's territory. Your downstream reader \
is the **comparch pass**, which will decompose this component \
into subcomponents and assign each subresponsibility to exactly \
one subcomponent. Write subresponsibility handles specific \
enough that comparch can draw clean code-territory boundaries \
around them — name the data each subresp owns, the operations \
it performs, and how it differs from sibling subresps within \
this same component. A subresp whose intent is a restatement of \
the parent responsibility in slightly different words adds zero \
information for comparch — it can't assign what it can't \
distinguish.

You will be given:

1. The component's name, role, and API intent (from the approved \
system architecture).
2. The list of top-level responsibilities assigned to this \
component, each with a stable ``resp_*`` ID.

Each subresponsibility names which of the component's top-level \
responsibilities it decomposes, via a ``<derived-from>`` block. \
The relationship is many-to-many within this component's scope.

# Output format

Output a single ``<subrequirements>`` block. Nothing else. \
Each ``<subresponsibility>`` has exactly one ``<name>``, exactly \
one ``<intent>``, and exactly one ``<derived-from>`` block \
containing one or more ``<resp>`` children with an ``id`` \
attribute:

    <subrequirements>
      <subresponsibility>
        <name>Card Tokenization</name>
        <intent>Convert raw card numbers into opaque tokens at \
entry and ensure the raw numbers never leave the boundary. All \
downstream code operates on tokens exclusively.</intent>
        <derived-from>
          <resp id="resp_payment01"/>
        </derived-from>
      </subresponsibility>
      <subresponsibility>
        <name>Retry Scheduling</name>
        <intent>Schedule delayed retries of failed operations, \
with exponential backoff and a hard cap. Serves both payment \
retries and invoice delivery retries.</intent>
        <derived-from>
          <resp id="resp_payment01"/>
          <resp id="resp_invoice02"/>
        </derived-from>
      </subresponsibility>
    </subrequirements>

# Rules

* Use the tag structure exactly as shown. Each ``<subresponsibility>`` \
has exactly one ``<name>``, exactly one ``<intent>``, and exactly \
one ``<derived-from>`` block. No other tags inside.
* ``<name>`` is a short identifier — typically 2 to 5 words, \
title case. Name the specific slice of work, not a restatement \
of the parent. "Card Tokenization" under "Payment Collection" \
names what this subresp specifically does; "Handle Payments" \
would just echo the parent. "Session Refresh" under \
"Authentication" names a distinct operation; "Manage Sessions" \
would be too broad for comparch to place.
* ``<intent>`` is a paragraph — typically 2 to 5 sentences. The \
comparch pass will read this intent to decide which subcomponent \
owns this subresponsibility. Name specific data, specific \
operations, specific failure modes. Describe what this \
subresponsibility covers at a finer granularity than its parent, \
and what it does not cover. Each subresp should name something \
the parent responsibility's intent doesn't already say — if \
comparch can't tell what code territory this subresp lives in, \
it's not pulling its weight.
* ``<derived-from>`` is **required** and must contain **at \
least one** ``<resp>`` child per subresponsibility. Each \
``<resp>`` carries an ``id`` attribute matching exactly one of \
this component's top-level responsibility IDs shown in the \
input list (the ``resp_*`` prefix plus the 8-character Crockford \
suffix).
* **Cross-component leaks are forbidden.** Every id in a \
``<derived-from>`` block must be one of the top-level resps \
assigned to this component. Referencing a resp that belongs to \
a different component is a parse error.
* A top-level resp may appear under multiple ``<derived-from>`` \
blocks — the relationship is many-to-many within this \
component's scope.
* **Every top-level resp in the input must be covered by at \
least one subresp.** Before emitting the list, mentally check \
that each parent resp ID appears in at least one \
``<derived-from>`` block. Missing coverage is a parse error.
* **Presentational components: rotate mirrored parent resps to \
UI-side articulation.** If this component is presentational, \
its top-level responsibilities are (by sysarch design) mirrors \
of responsibilities also claimed by one or more domain \
components — the same ``resp_*`` IDs appear on both sides. \
Your job for each mirrored parent resp is to decompose it into \
subresps that articulate **the presentational face of that \
responsibility**: what the user sees, how they interact with \
it, what view state the component maintains, what feedback \
and error affordances it provides, what structural editing or \
navigation it supports. The "presentational face" is whatever \
fits the component's medium — UI panels for a web client, \
commands and flags for a CLI, dashboards for an operator \
console, pages for a docs site. The domain side is \
decomposing the same parent resp into its mechanism/data \
articulation; you are decomposing it into its human-interface \
articulation. Both decompositions derive from the same parent \
resp IDs via ``<derived-from>``.
* When the prompt includes a "# Domain-parent context" section \
listing subresps already minted by the domain side of a \
mirrored resp, treat it as a **reference for how the domain \
articulated the parent** — useful so your UI-side subresps \
align coherently with the backing domain work. **Do not \
reference any of the domain-parent subresp ids in your \
``<derived-from>`` blocks** — subresp IDs are scoped to the \
component that minted them, and your ``<derived-from>`` \
targets are always the top-level parent resps assigned to \
*this* component. Your subresps are a parallel rotation of \
the same parent resps, not derived from the domain's \
subresps.
* Do not include meta-commentary about what you are doing. \
Output only the ``<subrequirements>`` block.
* Unescaped ``&`` and ``<`` in intent text are fine — the parser \
tolerates them.
"""


def render_system_prompt() -> str:
    """Return the subrequirements system prompt."""
    from backend.graph.prompts._change_summary import change_summary_instruction

    return _SYSTEM_PROMPT_TEMPLATE + change_summary_instruction()


def render_user_prompt(
    *,
    component_summary: str,
    parent_resps_summary: str,
    domain_parent_context: str | None = None,
    sibling_dep_context: str | None = None,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    prior_review: str | None = None,
    parse_error: str | None = None,
    vocab_summary: str = "",
    referenced_content_summary: str = "",
) -> str:
    """Build the user prompt for the subreqs generator.

    ``component_summary`` is the component's name + role + api-
    intent rendered as prompt-ready text. ``parent_resps_summary``
    is the list of top-level resps assigned to this component,
    each with a stable ID the LLM echoes into ``<derived-from>``
    blocks.

    ``domain_parent_context`` is optional and only populated when
    this component is presentational and one or more of its
    ``domain_parent`` edge targets already has minted subresps.
    Rendered as a clearly-labeled read-only block so the LLM can
    align its UI-side subresps with the domain-side work without
    duplicating it. Cross-component references remain forbidden by
    the validator — the context is advisory, not referenceable.

    The remaining parameters mirror the other bootstrap prompts.
    """
    parts: list[str] = []
    if vocab_summary and vocab_summary.strip():
        parts.append(vocab_summary.strip())
        parts.append("")
    if (
        referenced_content_summary
        and referenced_content_summary.strip()
        and referenced_content_summary.strip() != "(no external references)"
    ):
        parts.append(referenced_content_summary.strip())
        parts.append("")
    parts.append("# Component")
    parts.append("")
    parts.append(component_summary.strip() or "(component details missing)")
    parts.append("")
    parts.append("# Top-level responsibilities assigned to this component")
    parts.append("")
    parts.append(parent_resps_summary.strip() or "(no responsibilities assigned)")
    parts.append("")

    if sibling_dep_context and sibling_dep_context.strip():
        parts.append("# Sibling dependency context (read-only — already available here)")
        parts.append("")
        parts.append(
            "These are the sibling components this component depends on, as "
            "declared in the sysarch. Their published API intent is shown "
            "so you can avoid re-deriving responsibilities these deps "
            "already own — this component should *consume* that surface, "
            "not reimplement it. **Do not reference any of these deps' "
            "ids in your <derived-from> blocks** — the validator rejects "
            "cross-component leaks. This context is advisory only."
        )
        parts.append("")
        parts.append(sibling_dep_context.strip())
        parts.append("")

    if domain_parent_context and domain_parent_context.strip():
        parts.append("# Domain-parent context (read-only)")
        parts.append("")
        parts.append(
            "This presentational component presents the domain components "
            "below. Their already-minted subresponsibilities are shown so "
            "you can align your UI-side subresps with the domain-side "
            "work. **Do not reference any of these resp ids in your "
            "<derived-from> blocks** — they belong to a different "
            "component's scope and will be rejected as cross-component "
            "leaks. This context is advisory only."
        )
        parts.append("")
        parts.append(domain_parent_context.strip())
        parts.append("")

    prior = prior_pending or prior_approved
    if prior:
        parts.append("# Current version")
        parts.append("")
        parts.append(prior.strip())
        parts.append("")

    if feedback:
        parts.append("# User feedback")
        parts.append("")
        parts.append(feedback.strip())
        parts.append("")

    parts.extend(render_prior_review_section(prior_review))

    if parse_error:
        parts.append("# Previous output failed structural validation")
        parts.append("")
        parts.append(
            "Your previous response did not parse into a valid "
            "<subrequirements> block. The specific error was:"
        )
        parts.append("")
        parts.append(f"> {parse_error.strip()}")
        parts.append("")
        parts.append(
            "Fix the structure and re-emit the full "
            "<subrequirements> block. Keep the subresp set itself "
            "the same where possible — this retry is about format, "
            "not content."
        )
        parts.append("")

    parts.append("# Task")
    parts.append("")
    if parse_error:
        parts.append(
            "Re-emit the subrequirements as a valid <subrequirements> "
            "block addressing the structural error above. Output only "
            "the corrected block."
        )
    elif feedback and prior:
        parts.append(
            "Revise the subrequirements to address the user feedback "
            "above. Preserve structure where the feedback does not "
            "require a change. Output only the revised "
            "<subrequirements> block."
        )
    elif prior:
        parts.append(
            "Improve the subrequirements above. Fix any issues you "
            "notice with granularity, specificity, or coverage of the "
            "parent responsibilities. Output only the revised "
            "<subrequirements> block."
        )
    else:
        parts.append(
            "Write an initial subrequirements list for this "
            "component based on its assigned top-level responsibilities. "
            "Output only the <subrequirements> block."
        )

    return "\n".join(parts).rstrip() + "\n"


def format_component_summary(name: str, role: str, api_intent: str) -> str:
    """Render component metadata as a prompt-ready markdown block."""
    parts: list[str] = []
    parts.append(f"**{name}**")
    parts.append("")
    if role:
        parts.append("*Role:*")
        parts.append(role.strip())
        parts.append("")
    if api_intent:
        parts.append("*API intent:*")
        parts.append(api_intent.strip())
    return "\n".join(parts).rstrip()


def format_parent_resps_summary(resps: list[dict]) -> str:
    """Render assigned top-level resps as prompt-ready markdown.

    Each entry must carry ``id``, ``name``, ``content``. IDs are
    rendered prominently so the LLM echoes them verbatim into
    ``<derived-from>`` blocks.
    """
    if not resps:
        return "(no responsibilities assigned to this component)"
    lines: list[str] = []
    for resp in resps:
        rid = resp.get("id", "").strip() or "(unknown-id)"
        name = resp.get("name", "").strip() or "(unnamed)"
        intent = (resp.get("content") or "").strip()
        lines.append(f"- `{rid}` **{name}**: {intent}")
    return "\n".join(lines)


def format_domain_parent_context(parents: list[dict]) -> str:
    """Render domain-parent components + their subresps as prompt context.

    Each entry in ``parents`` must carry ``name`` (component
    display name) and ``subresps`` (a list of dicts with ``id``,
    ``name``, ``content``). Components with no minted subresps are
    skipped — the block only shows up when there's actual context
    to provide. Returns an empty string if no parents have
    subresps yet.

    IDs are rendered but the accompanying prose in the prompt
    system message tells the LLM these are read-only — the
    validator rejects any ``<derived-from>`` reference that
    crosses the component boundary, so the IDs are there for
    comprehension, not for citation.
    """
    sections: list[str] = []
    for parent in parents:
        subresps = parent.get("subresps") or []
        if not subresps:
            continue
        name = (parent.get("name") or "(unnamed)").strip()
        lines: list[str] = [f"## {name}", ""]
        for sub in subresps:
            sid = sub.get("id", "").strip() or "(unknown-id)"
            sname = sub.get("name", "").strip() or "(unnamed)"
            intent = (sub.get("content") or "").strip()
            lines.append(f"- `{sid}` **{sname}**: {intent}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def format_sibling_dep_context(deps: list[dict]) -> str:
    """Render sibling-dependency components + their surface as prompt context.

    Each entry in ``deps`` carries:

    - ``name``: the dep's display name.
    - ``api_intent``: the dep's ``pubapi`` fragment (its
      ``<api-intent>`` paragraph sysarch wrote at mint time).
    - ``responsibilities``: the top-level ``resp_*`` nodes assigned
      to the dep via ``decomposition`` edges at sysarch mint.
      Shape: list of ``{"id", "name", "content"}`` dicts. These
      are the dep's concern territory at the sysarch level — what
      it's scoped to handle.

    Both signals land at sysarch mint, so this block is reliably
    populated the first time any dependent's subreqs job fires.
    A dep is included when it has *either* an api_intent or at
    least one assigned responsibility; deps with neither are
    skipped.
    """
    sections: list[str] = []
    for dep in deps:
        name = (dep.get("name") or "(unnamed)").strip()
        api_intent = (dep.get("api_intent") or "").strip()
        resps = dep.get("responsibilities") or []
        if not api_intent and not resps:
            continue
        lines: list[str] = [f"## {name}", ""]
        if api_intent:
            lines.append("**API intent:**")
            lines.append("")
            lines.append(api_intent)
        if resps:
            if api_intent:
                lines.append("")
            lines.append("**Responsibilities assigned here:**")
            lines.append("")
            for r in resps:
                rid = r.get("id", "").strip() or "(unknown-id)"
                rname = r.get("name", "").strip() or "(unnamed)"
                intent = (r.get("content") or "").strip()
                lines.append(f"- `{rid}` **{rname}**: {intent}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
