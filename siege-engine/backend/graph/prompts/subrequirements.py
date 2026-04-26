"""Prompt template for the subrequirements (``subreqs_*``) draft.

A subreqs node is the per-component analogue of the reqs_* doc.
It takes a single component's sysarch entry (role + api-intent),
its assigned top-level responsibilities, and the in-scope feature
IDs reachable from those parent resps, and produces the list of
**atomic subresponsibilities** that the component's comparch pass
(Phase 4) will later map onto subcomponents.

Output format:

    <subrequirements>
      <subresponsibility>
        <name>Card Tokenization</name>
        <feats>
          <feat id="feat_payment01"/>
        </feats>
        <derived-from>
          <resp id="resp_payment01"/>
        </derived-from>
      </subresponsibility>
      …
    </subrequirements>

Parallel atom shape to ``<requirements>`` but scoped to one
component. Each subresp's ``<name>`` is the scope phrase verbatim
(no separate intent prose). ``<feats>`` lists the in-scope feat
IDs this concern implicates (many-to-many; an empty ``<feats/>``
is legal for component-emergent atoms with no direct feature
cause). ``<derived-from>`` lists which assigned parent resps this
subresp decomposes (also many-to-many).

The validator enforces:
  * Every ``<feat id=…>`` belongs to the in-scope feat set
    (cross-component leaks are parse errors).
  * Every ``<resp id=…>`` belongs to the assigned-parent-resp set
    (cross-component leaks are parse errors).
  * Every assigned parent resp appears in at least one
    ``<derived-from>`` (parent-resp coverage).
  * Every in-scope feat appears in at least one ``<feats>``
    (feat-coverage).
  * No two subresps share a normalized name (atom dedup).

See ``docs/architecture/v2-rearchitecture.md`` §Subrequirements
decomposition and ``docs/architecture/v2-roadmap.md`` Phase 3.
"""

from __future__ import annotations

from backend.graph.prompts._prior_framing import render_prior_review_section

_SYSTEM_PROMPT_TEMPLATE = """\
You are deciding whether — and how — to decompose this \
component's top-level responsibilities into **atomic \
subresponsibilities**. Your downstream reader is the **comparch \
pass**, which will draw subcomponent boundaries. Subresps are \
**optional**: a parent resp that fits cleanly inside a single \
subcomponent shouldn't be decomposed at all — it maps wholesale \
to that subcomp at comparch time. Only emit subresps for parent \
resps whose work is large or heterogeneous enough that comparch \
would need to spread them across multiple subcomponents.

Concretely: if a single subcomponent could plausibly own the \
entire parent resp, don't produce subresps for it. If you'd \
have to invent a subresp that paraphrases the parent resp's \
name with the same feat-set, you're decomposing for its own \
sake — drop it. A parent resp covered by exactly one subresp \
that mirrors its scope is a smell; either split it into two or \
more genuinely-distinct atoms, or omit subresps for that parent \
entirely.

When you do decompose, write each subresp as one concrete \
component-internal concern comparch could assign to a single \
subcomponent. Clustering is comparch's job, not yours; if your \
subresp set looks like the parent-resp list with different \
names, you haven't decomposed — you've renamed.

You will be given:

1. The component's name, role, and API intent (from the approved \
system architecture).
2. The list of top-level responsibilities assigned to this \
component, each with a stable ``resp_*`` ID and the bracketed \
list of feature IDs it implicates.
3. A ``# Features in scope`` reference table at the bottom of \
the prompt — the canonical ID-to-name map for every ``feat_*`` \
you may tag.

Each subresp names which parent resps it decomposes (via \
``<derived-from>``) and which in-scope features it implicates \
(via ``<feats>``). Both relationships are many-to-many within \
this component's scope. Parent resps **not** referenced by any \
subresp will be assigned wholesale to a single subcomponent at \
comparch time; that's the deliberate signal that no \
decomposition was needed.

# Output format

Emit two top-level blocks in this order: ``<introduction>`` \
and ``<subrequirements>``. The ``<introduction>`` is required — \
a short prose paragraph (2-4 sentences) capturing your initial \
thinking about how this component's responsibilities want to \
decompose: which parent resps cluster together, where the \
boundaries naturally fall, anything you noticed about scope or \
mirroring (for presentational components) before listing the \
subresps. Subsequent regens read this preamble as their starting \
context, so it has to be your own framing — not a summary of \
the schema.

Then exactly one ``<subrequirements>`` block. Each \
``<subresponsibility>`` has exactly one ``<name>``, exactly one \
``<feats>`` block, and exactly one ``<derived-from>`` block. \
``<feats>`` may be empty (``<feats/>``) for component-emergent \
atoms with no direct feature cause; ``<derived-from>`` must \
have at least one ``<resp>`` child:

    <introduction>
    Five parent resps. Payment Collection splits into three \
    distinct slices (tokenization, retry, ledger) — different \
    code, different storage. Audit Trail is a single concern \
    a single subcomponent will own end-to-end, so I'm not \
    decomposing it. Session Lifecycle is similar — fits in \
    one subcomp. The remaining two parent resps share retry \
    machinery, so I'll let one cross-cutting subresp handle \
    that and otherwise leave them un-decomposed.
    </introduction>
    <subrequirements>
      <subresponsibility>
        <name>Card Tokenization</name>
        <feats>
          <feat id="feat_payment01"/>
        </feats>
        <derived-from>
          <resp id="resp_payment01"/>
        </derived-from>
      </subresponsibility>
      <subresponsibility>
        <name>Retry Scheduling</name>
        <feats>
          <feat id="feat_payment01"/>
          <feat id="feat_invoice02"/>
        </feats>
        <derived-from>
          <resp id="resp_payment01"/>
          <resp id="resp_invoice02"/>
        </derived-from>
      </subresponsibility>
      <subresponsibility>
        <name>Settlement Ledger</name>
        <feats>
          <feat id="feat_payment01"/>
        </feats>
        <derived-from>
          <resp id="resp_payment01"/>
        </derived-from>
      </subresponsibility>
    </subrequirements>

Three subresps total — Payment Collection genuinely splits \
three ways, the cross-cutting Retry Scheduling pulls in its \
second parent (Invoicing), and the other parent resps \
(Audit Trail, Session Lifecycle, plus Invoicing's non-retry \
work) will be assigned wholesale to subcomps at comparch \
time. Resist the urge to add a one-to-one subresp for those.

# Rules

* Use the tag structure exactly as shown. Each \
``<subresponsibility>`` has exactly one ``<name>``, exactly one \
``<feats>``, and exactly one ``<derived-from>`` block. No other \
tags inside.
* **An empty ``<subrequirements/>`` block is legal.** If every \
parent resp fits in a single subcomponent, emit zero subresps. \
That's the right answer — no split needed.
* **Decompose only when one subcomp couldn't own the whole \
parent resp.** Before emitting any subresp, ask: could a single \
subcomponent reasonably own this parent resp end-to-end? If \
yes, don't write a subresp for it — leave it for comparch to \
assign wholesale. Write subresps only when the work is large \
or heterogeneous enough that you'd be forcing two separate \
code-territories into one box otherwise.
* **A parent resp covered by exactly one subresp is almost \
always wrong.** If you only emit one subresp for a parent, \
either the work was atomic (drop the subresp; let comparch \
assign the parent wholesale), or it actually splits two-or- \
more ways (emit the additional atoms). The only legitimate \
single-subresp case is a cross-cutting atom whose name and \
feat-set are strictly narrower than the parent's, derived from \
multiple parents.
* ``<name>`` is the **scope phrase verbatim** — a short noun \
phrase, typically 2 to 5 words, title case, naming one \
component-territory concern. "Card Tokenization" names the \
specific slice of work; "Handle Payments" would just echo the \
parent. The name is what comparch reads to decide subcomponent \
boundaries — make it concrete enough that comparch can place it \
without guessing what's inside. No two subresps in this \
component may share a normalized name.
* ``<feats>`` lists the in-scope feat IDs this concern \
implicates. Tag every feat that this subresp's work is partly \
responsible for, not just the "primary" one — many-to-many is \
expected, since a cross-cutting concern (retry scheduling, \
audit logging, idempotency) typically supports multiple \
features. Empty ``<feats/>`` is legal for component-emergent \
atoms (internal cache, plumbing, lifecycle hooks).
* **Cross-component leaks are forbidden in ``<feats>``.** Every \
``<feat id=…>`` must reference one of the in-scope features \
listed in the ``# Features in scope`` table. Referencing a feat \
not tagged on any of this component's parent resps is a parse \
error.
* ``<derived-from>`` is **required** on every subresp and must \
contain at least one ``<resp>`` child. Each ``<resp>`` carries \
an ``id`` attribute matching one of this component's top-level \
responsibility IDs shown in the input list.
* **Cross-component leaks are forbidden in ``<derived-from>``.** \
Every id must be one of the top-level resps assigned to this \
component. A top-level resp may appear under multiple \
``<derived-from>`` blocks — many-to-many within this \
component's scope.
* **Atomicity test.** A subresp tagged with the same set of \
feats as its only parent resp, with a name that paraphrases \
the parent, is not an atom — it's the parent in disguise. \
Either split it into two or more genuinely-distinct atoms, or \
drop the subresp entirely so comparch handles the parent \
wholesale.
* **Presentational components: rotate mirrored parent resps to \
UI-side articulation.** If this component is presentational, \
its top-level responsibilities are (by sysarch design) mirrors \
of responsibilities also claimed by one or more domain \
components — the same ``resp_*`` IDs appear on both sides. \
Your job for each mirrored parent resp is to decompose it into \
subresps that articulate **the presentational face of that \
responsibility**: what the user sees, how they interact with \
it, what view state the component maintains, what feedback and \
error affordances it provides, what structural editing or \
navigation it supports. The "presentational face" is whatever \
fits the component's medium — UI panels for a web client, \
commands and flags for a CLI, dashboards for an operator \
console, pages for a docs site. The domain side is decomposing \
the same parent resp into its mechanism/data articulation; you \
are decomposing it into its human-interface articulation. Both \
sides tag the same in-scope feats from a different angle.
* When the prompt includes a "# Domain-parent context" section \
listing subresps already minted by the domain side of a \
mirrored resp, treat it as a **reference for how the domain \
articulated the parent** — useful so your UI-side subresps \
align coherently with the backing domain work. **Do not \
reference any of the domain-parent subresp ids in your \
``<derived-from>`` blocks** — subresp IDs are scoped to the \
component that minted them; your ``<derived-from>`` targets are \
always the top-level parent resps assigned to *this* component.
* Do not include meta-commentary about what you are doing. \
Output only the ``<introduction>`` followed by the \
``<subrequirements>`` block.
"""


def render_system_prompt() -> str:
    """Return the subrequirements system prompt."""
    from backend.graph.prompts._change_summary import change_summary_instruction

    return _SYSTEM_PROMPT_TEMPLATE + change_summary_instruction()


def render_user_prompt(
    *,
    component_summary: str,
    parent_resps_summary: str,
    in_scope_feats_summary: str,
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
    each with a stable ID and a bracketed list of the feat IDs it
    implicates — both echoed into the subresps' ``<derived-from>``
    and ``<feats>`` blocks. ``in_scope_feats_summary`` is the
    canonical ID-to-name reference table for every feat that may
    appear in a ``<feats>`` block (the union of feats reachable
    from this component's parent resps).

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

    parts.append("# Features in scope")
    parts.append("")
    parts.append(
        "Reference table for the ``<feats>`` blocks below — these "
        "are the only feat IDs you may tag (the union of features "
        "reachable from this component's assigned parent resps). "
        "Every feat below must appear in at least one subresp's "
        "``<feats>`` (feat-coverage)."
    )
    parts.append("")
    parts.append(in_scope_feats_summary.strip() or "(no in-scope features)")
    parts.append("")

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

    Each entry must carry ``id``, ``name``, and ``feat_ids`` (a
    list of feat IDs implicating this resp via the ``feat → resp``
    decomposition edges). IDs are rendered prominently so the LLM
    echoes them verbatim into ``<derived-from>`` blocks; the
    bracketed feat IDs reinforce which feats each resp implicates,
    so the LLM can cluster atoms by feat-cohort within a parent.
    """
    if not resps:
        return "(no responsibilities assigned to this component)"
    lines: list[str] = []
    for resp in resps:
        rid = resp.get("id", "").strip() or "(unknown-id)"
        name = resp.get("name", "").strip() or "(unnamed)"
        feat_ids = list(resp.get("feat_ids") or [])
        if feat_ids:
            tag_suffix = f" [{', '.join(feat_ids)}]"
        else:
            tag_suffix = " []"
        lines.append(f"- `{rid}` **{name}**{tag_suffix}")
    return "\n".join(lines)


def format_in_scope_feats_summary(feats: list[dict]) -> str:
    """Render the in-scope feat reference table.

    Each entry must carry ``id`` and ``name``. Output is a flat
    bullet list — the ``# Features in scope`` section in the user
    prompt is the LLM's authoritative ID-to-name map for echoing
    feat IDs into ``<feats>`` blocks. Intent prose is intentionally
    omitted; the canonical handle is the name + ID, and adding the
    intent here would duplicate context already carried by the
    parent-resp summary's bracketed feat IDs.
    """
    if not feats:
        return "(no in-scope features)"
    lines: list[str] = []
    for feat in feats:
        fid = feat.get("id", "").strip() or "(unknown-id)"
        name = feat.get("name", "").strip() or "(unnamed)"
        lines.append(f"- `{fid}` **{name}**")
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
            lines.append(f"- `{sid}` **{sname}**")
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
                lines.append(f"- `{rid}` **{rname}**")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
