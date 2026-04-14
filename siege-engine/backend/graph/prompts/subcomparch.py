"""Prompt template for the subcomponent architecture (``subcomparch``) draft.

Phase 5 counterpart to :mod:`backend.graph.prompts.comparch`. Each
subcomponent ``comp_*`` (a ``comp`` tier node whose ``parent_id``
points at another ``comp``) gets its own architecture doc. The
subcomparch is smaller than the top-level comparch because
subcomponents are leaves in the component-tier tree: they cannot
decompose further (the reducer's depth cap at
``_enforce_comp_depth_cap`` enforces this) and they don't mint new
policies. The arch doc has exactly four sections in fixed order:
techspec, public surface, private surface, and dependencies.

Output format:

    <subcomparch>
      <technical-specification>…role-level techspec…</technical-specification>
      <public-surface>…types, signatures, events visible to the \
parent's other subs + parent's dependents…</public-surface>
      <private-surface>…internal helpers, only visible inside \
this subcomponent's own impl node…</private-surface>
      <dependencies>
        <dep to="sibling_sub_alias"/>   <!-- local alias of a \
same-parent sibling -->
        <dep to="comp_parent_sibling1"/>  <!-- real comp_* ID of \
one of the parent's siblings -->
      </dependencies>
    </subcomparch>

Four sections in fixed order. All four are fragments (persistent,
transcluded into dependents' regen prompts). No mint-time
directives — there is no ``<subcomponents>`` or ``<sub-dependencies>``
section because subcomponents are leaves, and no ``<policies>``
section because they don't introduce new cross-cutting invariants.

Design notes:

- ``<dependencies>`` allows **mixed targets** in a single section.
  A ``to="..."`` attribute that starts with ``comp_`` is a real
  sibling-of-parent ``comp_*`` ID; anything else is a local alias
  of a same-parent sibling subcomponent. The validator
  disambiguates at parse time based on the ``comp_`` prefix.
- Local aliases for sibling subcomponents are the **slugified**
  form of the minted subcomponent's display name (e.g.
  ``SessionStore`` → ``session_store``). The Phase 5 handler
  resolves the alias back to the real ``comp_*`` ID at mint time.
- ``<dependencies>`` can be empty when the subcomponent is a true
  leaf with no external surface interactions.
- Subcomponents inherit their kind (domain / presentational) from
  the owning top-level component — there is no ``<kind>`` tag.
- The techspec should be **narrower** than the parent's — it
  describes this subcomponent's slice of the component's tech
  choices, not the whole component. Do not duplicate the parent
  techspec verbatim.
- The public surface is what sibling subs and the parent's
  external dependents see. The private surface is only for the
  subcomponent's own impl node down at the Phase 6 layer.

See ``docs/architecture/v2-rearchitecture.md`` §Architecture
documents are parseable and ``docs/architecture/v2-roadmap.md``
Phase 5.
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are a senior software architect producing the **subcomponent \
architecture document** for a single subcomponent inside a larger \
component in a software project. You will be given the owning \
top-level component's metadata (techspec, public surface, private \
surface), this subcomponent's name + role + API intent from the \
parent's comparch decomposition, the subresponsibilities \
assigned to this subcomponent, the list of same-parent sibling \
subcomponents it may declare local dependencies on (each shown \
with its real ``comp_*`` ID), the list of parent-sibling \
top-level components it may declare cross-component dependencies \
on (also shown with real ``comp_*`` IDs), the public surfaces of \
siblings/parent-siblings that are already fully architected, and \
optionally prior approved / pending drafts, user feedback, and \
parse-validate errors.

Your job is to produce a single ``<subcomparch>`` block \
containing four sections in a fixed order: a role-level technical \
specification for this subcomponent, its public surface, its \
private surface, and its dependencies. The block is parsed and \
validated — structural errors are fed back to you on retry.

# Output format

Emit exactly one ``<subcomparch>`` block with these four children \
in this order: ``<technical-specification>`` → \
``<public-surface>`` → ``<private-surface>`` → ``<dependencies>``. \
Example (abbreviated):

    <subcomparch>
      <technical-specification>
    Python module implementing an in-memory LRU cache on top of \
    the parent component's shared Redis client. Entries carry a \
    monotonic version counter set by the parent's write path; \
    cache reads compare-and-invalidate against the underlying \
    store when the counter drifts.
      </technical-specification>
      <public-surface>
    Sibling subs and parent dependents call into this \
    subcomponent via:

    ```python
    def get(key: str) -> CachedValue | None: ...
    def put(key: str, value: CachedValue) -> None: ...
    def invalidate(key: str) -> None: ...
    ```

    No events emitted — this is a pure read-through cache.
      </public-surface>
      <private-surface>
    Internal helpers only visible inside this subcomponent's \
    own impl node:

    ```python
    def _touch(key: str) -> None: ...
    def _evict_stale(now: datetime) -> int: ...
    ```
      </private-surface>
      <dependencies>
        <dep to="comp_session9"/>
        <dep to="comp_audit999"/>
      </dependencies>
    </subcomparch>

# Rules

## Structure

* Emit **exactly one** ``<subcomparch>`` root block. Nothing \
before, nothing after.
* The four children **must appear in this order**: \
``<technical-specification>`` → ``<public-surface>`` → \
``<private-surface>`` → ``<dependencies>``. Out-of-order sections \
are a structural error.
* No unknown top-level children under ``<subcomparch>``. \
Specifically, ``<policies>`` is rejected with an explicit error \
because subcomponents don't have policies, and \
``<subcomponents>`` / ``<sub-dependencies>`` are rejected because \
subcomponents can't decompose further.

## Fragment sections (techspec / pubapi / privapi)

* ``<technical-specification>`` is a **role-level** paragraph \
describing this subcomponent's slice of the parent component's \
technology and architecture choices. Narrow the parent techspec \
— don't duplicate it. If the parent techspec says "Python on \
FastAPI with PostgreSQL via SQLAlchemy", this subcomponent's \
techspec adds what it specifically owns within that stack, not a \
re-statement of the full sentence.
* ``<public-surface>`` is the API the subcomponent exposes to \
sibling subcomponents and to the parent component's external \
dependents. Types, function signatures, method signatures, \
events. Code-shaped content lives in fenced code blocks; the \
parser does not inspect the code so any language is fine. Only \
surface that callers outside this subcomponent will see; \
internal helpers belong in ``<private-surface>``.
* ``<private-surface>`` is internal types and helpers visible \
only to this subcomponent's own impl node (Phase 6), not to \
sibling subs or the parent's dependents. Same fenced-code-block \
convention as the public surface.
* All three fragment sections must be non-empty. Do not put \
nested XML tags inside them — only prose and fenced code blocks.

## Dependencies (real comp_* IDs only)

* ``<dependencies>`` is a single section holding ``<dep>`` edges \
from this subcomponent to other components. Every target is a \
real ``comp_*`` ID — the alias scheme is NOT used at this tier \
because both kinds of allowed targets already exist as minted \
nodes when subcomparch is generated.
* Two allowed target kinds, both written the same way:
  - **Same-parent sibling subcomponents**: pick from the list of \
    ``comp_*`` IDs the input context shows under "Same-parent \
    sibling subcomponents". Example: \
    ``<dep to="comp_session9"/>``.
  - **Parent's sibling top-level components**: pick from the \
    list of ``comp_*`` IDs the input context shows under \
    "Parent's sibling top-level components". Example: \
    ``<dep to="comp_audit999"/>``.
* At most one ``<dep>`` per target (duplicates rejected).
* No self-deps: you may not reference your own ``comp_*`` ID.
* ``<dependencies>`` may be **empty** when this subcomponent is a \
true leaf with no external surface interactions. Emit \
``<dependencies></dependencies>``.
* The validator rejects unknown IDs and any ``to`` attribute \
that is not a ``comp_*`` prefix with an explicit allowlist error \
on retry.

## Meta-rules

* Do not include commentary about what you are doing or how you \
arrived at the design. Output only the ``<subcomparch>`` block.
* Unescaped ``&`` and ``<`` inside fragment-section text (outside \
the XML tags themselves) are tolerated by the parser.
* Do not emit a ``<policies>`` section. Subcomponents are leaves \
in the component tier and do not introduce new cross-cutting \
invariants. If you think a new policy is needed, that is \
structural feedback on the parent component's comparch and \
belongs there.
* Do not emit a ``<subcomponents>`` or ``<sub-dependencies>`` \
section. Subcomponents cannot decompose further — the reducer \
enforces a two-level ``comp_*`` depth cap. Any internal structure \
you want to describe belongs in the ``<private-surface>`` \
section as prose or code, not as structural XML.
"""


def render_user_prompt(
    *,
    subcomponent_summary: str,
    parent_component_summary: str,
    subresps_summary: str,
    sibling_subcomps_summary: str,
    parent_sibling_comps_summary: str,
    dep_pubapi_summary: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    parse_error: str | None = None,
) -> str:
    """Build the user prompt for the subcomparch generator.

    All context sections are passed in as pre-formatted strings.
    The stage 2 ``regen_context`` helper produces them from the
    subcomponent's DB state via
    :func:`format_regen_context_for_sub`; for unit tests they can
    be supplied directly.

    - ``subcomponent_summary``: the subcomponent's own name + role
      + api-intent (content of the skeletal techspec / pubapi
      fragments comparch_mint seeded).
    - ``parent_component_summary``: the owning top-level
      component's identity, techspec, public surface, and
      private surface — this subcomponent's cover for the
      parent's slice of the system.
    - ``subresps_summary``: the subresponsibilities this
      subcomponent owns (from the comparch decomposition pass).
    - ``sibling_subcomps_summary``: same-parent sibling
      subcomponents listed by real ``comp_*`` ID + name + role.
      Allowed targets for ``<dep to="comp_..."/>`` entries.
    - ``parent_sibling_comps_summary``: top-level components
      other than this subcomponent's parent, listed by real
      ``comp_*`` ID + name. Also allowed targets for
      ``<dep to="comp_..."/>`` entries.
    - ``dep_pubapi_summary``: public-surface fragments of any
      siblings / parent-siblings whose arch docs are already
      minted. Empty on first-run subcomparch.
    - ``prior_approved`` / ``prior_pending`` / ``feedback`` /
      ``parse_error``: standard regen/retry context shared with
      every other bootstrap prompt.
    """
    parts: list[str] = []
    parts.append("# Subcomponent")
    parts.append("")
    parts.append(subcomponent_summary.strip() or "(subcomponent details missing)")
    parts.append("")
    parts.append("# Owning parent component")
    parts.append("")
    parts.append(parent_component_summary.strip() or "(parent details missing)")
    parts.append("")
    parts.append("# Subresponsibilities assigned to this subcomponent")
    parts.append("")
    parts.append(subresps_summary.strip() or "(no subresponsibilities assigned)")
    parts.append("")
    parts.append("# Same-parent sibling subcomponents (allowed <dep> targets)")
    parts.append("")
    parts.append(sibling_subcomps_summary.strip() or "(no same-parent sibling subcomponents)")
    parts.append("")
    parts.append("# Parent's sibling top-level components (allowed <dep> targets)")
    parts.append("")
    parts.append(parent_sibling_comps_summary.strip() or "(no parent-sibling top-level components)")
    parts.append("")

    if dep_pubapi_summary and dep_pubapi_summary.strip():
        parts.append("# Dependency public surfaces")
        parts.append("")
        parts.append(
            "These are the public-surface fragments of siblings "
            "or parent-siblings you may depend on. Use them to "
            "ground your own public-surface and technical-"
            "specification sections in the real shapes they "
            "expose."
        )
        parts.append("")
        parts.append(dep_pubapi_summary.strip())
        parts.append("")

    if prior_approved:
        parts.append("# Previously-approved subcomponent architecture doc")
        parts.append("")
        parts.append(prior_approved.strip())
        parts.append("")

    if prior_pending:
        parts.append("# Current draft (not yet approved)")
        parts.append("")
        parts.append(prior_pending.strip())
        parts.append("")

    if feedback:
        parts.append("# User feedback")
        parts.append("")
        parts.append(feedback.strip())
        parts.append("")

    if parse_error:
        parts.append("# Previous output failed structural validation")
        parts.append("")
        parts.append(
            "Your previous response did not parse into a valid "
            "<subcomparch> block. The specific error was:"
        )
        parts.append("")
        parts.append(f"> {parse_error.strip()}")
        parts.append("")
        parts.append(
            "Fix the structure and re-emit the full <subcomparch> "
            "block. Preserve the architectural decisions where the "
            "feedback does not require a change — this retry is "
            "about format, not content."
        )
        parts.append("")

    parts.append("# Task")
    parts.append("")
    if parse_error:
        parts.append(
            "Re-emit the subcomponent architecture doc as a valid "
            "<subcomparch> block addressing the structural error "
            "above. Output only the corrected <subcomparch> block."
        )
    elif feedback and (prior_pending or prior_approved):
        parts.append(
            "Revise the subcomponent architecture doc to address "
            "the user feedback above. Preserve the design where "
            "the feedback does not require a change. Output only "
            "the revised <subcomparch> block."
        )
    elif prior_pending or prior_approved:
        parts.append(
            "Regenerate the subcomponent architecture doc from "
            "scratch based on the context above. Output only the "
            "<subcomparch> block."
        )
    else:
        parts.append(
            "Write an initial architecture doc for this "
            "subcomponent based on its context above. Output "
            "only the <subcomparch> block."
        )

    return "\n".join(parts).rstrip() + "\n"
