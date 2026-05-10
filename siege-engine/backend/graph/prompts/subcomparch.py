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

from backend.graph.prompts._change_summary import change_summary_instruction
from backend.graph.prompts._prior_framing import render_prior_review_section

SYSTEM_PROMPT = """\
You are producing the **subcomponent architecture document** for \
a single subcomponent — a leaf in the component tree. This is \
the **final articulation layer** before implementation. Your \
``<public-surface>`` fragment is what sibling subcomponents and \
the parent's external dependents will call — if it's vague, \
every caller must guess interface contracts. Your \
``<technical-specification>`` is what the impl node will build \
against — every line of vagueness here becomes a guess in the \
implementation, and there are no more tiers to correct it.

You will be given the owning top-level component's metadata \
(techspec, public surface, private surface), this subcomponent's \
name + role + API intent from the parent's comparch \
decomposition, the subresponsibilities assigned to this \
subcomponent, the list of same-parent sibling subcomponents it \
may declare local dependencies on (each shown with its real \
``comp_*`` ID), the list of parent-sibling top-level components \
it may declare cross-component dependencies on (also shown with \
real ``comp_*`` IDs), the public surfaces of siblings/parent-\
siblings that are already fully architected, and optionally \
prior approved / pending drafts, user feedback, and parse-\
validate errors.

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
technology and architecture choices. The impl node will read \
this to decide what code to write — what libraries, patterns, \
and data structures this specific subcomponent uses. Narrow the \
parent techspec to just this subcomponent's slice; don't \
duplicate it. If the parent techspec says "Python on FastAPI \
with PostgreSQL via SQLAlchemy", this subcomponent's techspec \
adds what it specifically owns within that stack (which tables, \
which async patterns, which validation approach), not a \
re-statement of the full sentence.
* Structure the spec as paragraphs separated by a blank line \
(``\n\n``) when it runs more than a sentence or two — one \
paragraph per concern. Don't use bullet lists or headings; the \
downstream renderer splits on blank lines and wraps each \
paragraph in its own block.
* ``<public-surface>`` is the **only API** sibling subcomponents \
and the parent component's external dependents will see. Types, \
function signatures, method signatures, events. Code-shaped \
content lives in fenced code blocks; any language is fine. \
Internal helpers belong in ``<private-surface>``.
* **Signatures are non-negotiable.** This is the leaf tier — \
impl writes its types, parameters, and return shapes directly \
off these entries; listing method names without signatures \
forces every caller to guess the contract, and each caller's \
guess diverges. Every callable entry in ``<public-surface>`` \
must show:
  - parameter types (or schema-shape for events / payloads),
  - return type, including the **error variant** when the call \
    can fail (``Result[T, ErrKind]``, ``T | None``, typed \
    exception list — pick whichever convention matches the \
    parent's tech stack and stay consistent),
  - whether the call is sync or async (must agree with the \
    parent comparch's techspec — sync sub on an async parent \
    is a defect),
  - any side effect: events emitted, state mutated, durable \
    writes, network calls, named explicitly rather than \
    buried in prose.
A pubapi entry that's just a method name with a one-line \
comment is incomplete; rewrite it as a full signature even if \
that means inventing a small named type to hold the shape.
* ``<private-surface>`` is internal types and helpers visible \
**only** to this subcomponent's own impl node, not to sibling \
subs or the parent's dependents. This is the impl node's \
private toolkit — the helpers, internal types, and data \
structures it will implement but not expose. Same fenced-code-\
block convention as the public surface.
* **Name internal data structures, not just helpers.** Subcomparch \
is impl's last source of truth for the named types it will \
introduce. If your techspec mentions an entry that "carries a \
monotonic version counter" or a queue that "buffers pending \
events", ``<private-surface>`` should name the type \
(``CacheEntry``, ``PendingEventBuffer``) and its shape — not \
just helper functions that operate on it. Internal helpers \
without the data structures they manipulate leave impl re-\
deriving the shape, and any sibling reaching across via the \
public surface ends up with a different mental model.
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

## Reconciliation pass — do this before emitting

Treat the four sections as one document and check them against \
each other. The most common defect at this tier is internal \
contradiction: techspec promises one thing, pubapi can't surface \
it, privapi has no shape for what techspec describes. Run these \
five scans before emitting.

* **Surface closure (both directions).** *Pass A — every \
techspec claim surfaces somewhere.* For every behavior, side \
effect, persisted value, emitted event, or return shape your \
``<technical-specification>`` describes, identify the \
``<public-surface>`` entry (callable from outside) or \
``<private-surface>`` entry (callable from this sub's impl) \
that mounts it. A techspec sentence with no corresponding \
surface entry is half-done — siblings have no way to call into \
the behavior, impl has no signature to write against. *Pass B \
— every surface entry is grounded.* For each pubapi/privapi \
entry, the techspec or your owns-summary slice must describe \
why it exists. Entries without a "this is here because…" \
anchor are filler and inflate the contract impl has to honor.
* **Failure-mode observability through pubapi.** Subcomparch \
has no separate ``<failure-surface>`` section, so failure \
modes thread through pubapi. For every failure or partial-\
success scenario your techspec describes (and any failure \
inherited from the parent comparch's failure-surface entries \
that touch resps you own), confirm a ``<public-surface>`` \
entry exposes it: an error variant in a tagged-tuple return, \
a typed exception, an event a caller can subscribe to, a \
status field they can inspect. The most common shape of this \
defect: techspec mentions partial-failure or rate-limit \
rejection, but the corresponding pubapi function returns a \
bare success type or an opaque error atom that strips the \
discriminating detail. Either expand the return shape, or \
strike the failure mode from the techspec — silent failures \
with no public observability are a worse outcome than \
admitting the limitation.
* **Dependency grounding.** For each ``<dep to="comp_..."/>``, \
confirm the techspec or a pubapi/privapi entry describes how \
this sub actually uses the target — what data flows, which \
sibling/parent-sibling pubapi gets called, what event gets \
subscribed to. Symmetrically, walk the techspec and pubapi \
prose for any cross-comp call site implied by the text and \
confirm a corresponding ``<dep>`` exists. An ungrounded \
``<dep>`` is either spurious (delete it) or evidence of \
unwritten prose (write it). An implicit cross-comp reference \
without a declared dep mis-leads impl about what it can \
import.
* **Co-owner seam visibility.** Your owns-summary may show a \
parent resp co-owned by a sibling sub (UI flow split or read/\
write path split). When that's true, ``<public-surface>`` \
must make your slice readable on its own — a caller looking \
at your pubapi alone should be able to tell which side of the \
seam (input vs validate, read-path vs write-path, etc.) they \
are calling into. Method names + return shapes that could \
plausibly belong to either co-owner are the defect; rename or \
restructure until the seam is unambiguous from the surface \
alone.
* **Rationale, not inventory.** Re-read the techspec, the \
pubapi prose between code blocks, and the privapi prose. \
Anywhere the text reads as a list of contents or category-\
speak ("handles X", "manages Y", "contains the helpers for \
Z"), rewrite it to name what's distinctive about this sub's \
slice — concrete actions, specific data shapes, specific \
concurrency or persistence patterns. Inventory framing reads \
as filler downstream and produces vague impl. The narrowing \
prompt isn't "describe what this sub contains"; it's "name \
what makes this sub's slice of the parent's stack distinct".

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
""" + change_summary_instruction()


def format_domain_parent_surface_for_sub(
    parents: tuple,
    techspecs: dict[str, str],
    pubapis: dict[str, str],
    fanins: dict[str, str] | None = None,
) -> str:
    """Render the Phase 6 "grandparent-domain" context block for a sub.

    Thin wrapper around
    :func:`backend.graph.prompts.comparch.format_domain_parent_surface`
    — the per-parent rendering rules are identical; only the
    framing prose around the block (emitted by ``render_user_prompt``)
    differs. Subcomponents of a presentational parent inherit the
    same domain-parent bundle their parent would see at its own
    comparch regen, so sharing the renderer keeps the two tiers'
    output identical down to whitespace. Phase 7 fan-in content
    is threaded through the same way.
    """
    from backend.graph.prompts.comparch import format_domain_parent_surface

    return format_domain_parent_surface(parents, techspecs, pubapis, fanins)


def render_user_prompt(
    *,
    subcomponent_summary: str,
    parent_component_summary: str,
    owns_summary: str,
    sibling_subcomps_summary: str,
    parent_sibling_comps_summary: str,
    dep_pubapi_summary: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    prior_review: str | None = None,
    parse_error: str | None = None,
    vocab_summary: str = "",
    domain_parent_surface: str = "",
    referenced_content_summary: str = "",
    project_techspec: str = "",
    project_policies: str = "",
    project_dependencies: str = "",
    project_domain_parents: str = "",
    parent_policies: str = "",
    parent_failure_surface: str = "",
    related_features_summary: str = "",
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
    - ``owns_summary``: the parent responsibilities (and per-resp
      feat slices) this subcomponent claims, as declared in the
      parent's comparch ``<owns>`` block. Walked from incoming
      decomposition edges (resp → sub, feat → sub) at format time.
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
    project_sysarch_blocks: list[tuple[str, str]] = []
    if project_techspec and project_techspec.strip():
        project_sysarch_blocks.append(("Techspec (project-wide tech baseline)", project_techspec))
    if project_policies and project_policies.strip():
        project_sysarch_blocks.append(("Top-level policies", project_policies))
    if project_dependencies and project_dependencies.strip():
        project_sysarch_blocks.append(("Dependency graph", project_dependencies))
    if project_domain_parents and project_domain_parents.strip():
        project_sysarch_blocks.append(
            ("Domain-parent edges (presentational → domain)", project_domain_parents)
        )
    if project_sysarch_blocks:
        parts.append("# Project sysarch (non-component-specific context)")
        parts.append("")
        parts.append(
            "These are the project-wide sysarch sections that apply "
            "to every subcomp — the tech stack, top-level policies, "
            "the inter-component dependency graph, and the "
            "presentational→domain mapping. Your subcomp's choices "
            "must be consistent with all of these: same stack, "
            "policies you're a candidate for honoured, dependencies "
            "matching the graph below."
        )
        parts.append("")
        for heading, body in project_sysarch_blocks:
            parts.append(f"## {heading}")
            parts.append("")
            parts.append(body.strip())
            parts.append("")
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
    parts.append("# Subcomponent")
    parts.append("")
    parts.append(subcomponent_summary.strip() or "(subcomponent details missing)")
    parts.append("")
    parts.append("# Owning parent component")
    parts.append("")
    parts.append(parent_component_summary.strip() or "(parent details missing)")
    parts.append("")
    if parent_policies and parent_policies.strip():
        parts.append("## Parent component-local policies")
        parts.append("")
        parts.append(
            "Cross-cutting policies the parent comparch declared. "
            "Your subcomp inherits these — when your subcomp's code "
            "would be a candidate site for one, honor it; if a "
            "policy doesn't apply, name why explicitly so the "
            "reviewer can confirm."
        )
        parts.append("")
        parts.append(parent_policies.strip())
        parts.append("")
    if parent_failure_surface and parent_failure_surface.strip():
        parts.append("## Parent component failure surface")
        parts.append("")
        parts.append(
            "Residual risks the parent comparch documented. Your "
            "subcomp's surfaces and invariants should be coherent "
            "with these — your owned slice contributes to (or "
            "guards) failure modes the parent already named."
        )
        parts.append("")
        parts.append(parent_failure_surface.strip())
        parts.append("")
    parts.append("# Parent responsibilities + feat slices this subcomponent claims")
    parts.append("")
    parts.append(
        "Read from the parent comparch's ``<owns>`` block (one entry "
        "per parent resp this subcomp claims, plus the feat-slice "
        "narrowed within that resp). Multi-owner is allowed: the "
        "same parent resp may also be claimed by sibling subcomps "
        "(each owning a different feat slice). Use this to anchor "
        "what code territory this subcomponent is for."
    )
    parts.append("")
    parts.append(
        owns_summary.strip() or "(this subcomponent does not anchor any parent responsibility)"
    )
    parts.append("")
    parts.append("# Same-parent sibling subcomponents (allowed <dep> targets)")
    parts.append("")
    parts.append(sibling_subcomps_summary.strip() or "(no same-parent sibling subcomponents)")
    parts.append("")
    parts.append("# Parent's sibling top-level components (allowed <dep> targets)")
    parts.append("")
    parts.append(parent_sibling_comps_summary.strip() or "(no parent-sibling top-level components)")
    parts.append("")

    if domain_parent_surface and domain_parent_surface.strip():
        parts.append("# Grandparent domain context (your parent presents)")
        parts.append("")
        parts.append(
            "Your owning parent component is **presentational** and "
            "carries ``domain_parent`` edges to the domain components "
            "below. Those edges were drawn at sysarch time to mark "
            "the parent as a primary view into that domain content. "
            "Because subcomponents inherit their ``kind`` from the "
            "parent, this block reaches you through the parent — "
            "you do not own these edges directly, but you must align "
            "your own ``<technical-specification>`` and "
            "``<public-surface>`` with the shapes the domain side "
            "exposes. If you need behavior that isn't on the domain "
            "side yet, route through the parent component's own "
            "``<dependencies>`` (one level up) rather than duplicating "
            "domain state into this subcomponent.\n\n"
            "Some domain parents below include **two views**: the "
            "top-down technical specification / public surface "
            "(the contract) and a bottom-up fan-in synthesis (the "
            "built reality, articulated from the actual impls). "
            "Prefer the built view when they drift, and flag the "
            "drift in your own ``<technical-specification>`` "
            "rather than silently picking one side."
        )
        parts.append("")
        parts.append(domain_parent_surface.strip())
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

    if related_features_summary and related_features_summary.strip():
        parts.append("# Related features (deep context)")
        parts.append("")
        parts.append(
            "Features reachable via the decomposition walk from the "
            "parent resps this subcomponent claims via its ``<owns>`` "
            "slice. You do not reference feature IDs directly — this "
            "is grounding for what user-visible work this sub "
            "ultimately serves."
        )
        parts.append("")
        parts.append(related_features_summary.strip())
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
    elif feedback and prior:
        parts.append(
            "Revise the subcomponent architecture doc to address "
            "the user feedback above. Preserve the design where "
            "the feedback does not require a change. Output only "
            "the revised <subcomparch> block."
        )
    elif prior:
        parts.append(
            "Improve the subcomponent architecture doc above. Fix "
            "any issues you notice with the techspec, public surface, "
            "private surface, or dependencies. Output only the "
            "revised <subcomparch> block."
        )
    else:
        parts.append(
            "Write an initial architecture doc for this "
            "subcomponent based on its context above. Output "
            "only the <subcomparch> block."
        )

    return "\n".join(parts).rstrip() + "\n"
