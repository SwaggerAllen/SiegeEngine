"""Prompt template for the component-architecture (``comparch``) draft.

The comparch pass is the Phase 4 per-component deep dive. Each
top-level ``comp_*`` gets an architecture doc that describes its
role-level techspec, public/private API surfaces, component-local
policies, external dependencies to sibling top-level components,
and its own subcomponent decomposition. The arch doc is approved
as a unit; on approval its fragment sections project into five
transcluded fragments and its mint-time sections project into
subcomponent ``comp_*`` mints, component-local ``policy_*`` mints,
and edge emissions.

Output format (parsed by :mod:`backend.graph.parsers.xml_sections`
and validated by
:func:`backend.graph.parsers.validators.validate_arch_doc`):

    <comparch>
      <technical-specification>…role-level techspec…</technical-specification>
      <public-surface>…types / signatures / events…</public-surface>
      <private-surface>…internal types + helpers…</private-surface>
      <policies>
        <policy>
          <name>…</name>
          <trigger>…</trigger>
          <required>resp_abc12345</required>
          <rationale>…</rationale>
        </policy>
      </policies>
      <dependencies>
        <dep to="comp_sibling1"/>
      </dependencies>
      <subcomponents>
        <subcomponent alias="cache">
          <name>CacheLayer</name>
          <role>…</role>
          <api-intent>…</api-intent>
          <responsibilities>
            <resp id="resp_sub_xyz"/>
          </responsibilities>
          <foundation/>
        </subcomponent>
      </subcomponents>
      <sub-dependencies>
        <dep from="cache" to="foundation_sub"/>
      </sub-dependencies>
    </comparch>

Seven sections in fixed order. First five are fragments
(persistent, transcluded into dependents' regen prompts). Last
two are mint-time directives: ``<subcomponents>`` mints
``comp_*`` children and ``<sub-dependencies>`` emits dependency
edges between them. Both may be empty for un-fanned-out
components that will grow a single ``impl_*`` leaf instead.

Design notes:

- ``<dependencies>`` uses **real** ``comp_*`` IDs (sibling top-level
  components are globally unique and already minted by sysarch).
- ``<sub-dependencies>`` uses **local aliases** (subcomponents are
  minted by the mint handler at approval time, so their IDs don't
  exist yet at generation time).
- Subcomponents inherit their kind (domain / presentational) from
  the owning component and do not redeclare it — a presentational
  top-level component's subcomponents are all presentational by
  construction.
- Policies come before dependencies for the same reason as sysarch:
  a policy can induce a dep edge, so the LLM reasons about policies
  first and the resulting deps land naturally in the next section.

See ``docs/architecture/v2-rearchitecture.md`` §Architecture
documents are parseable, §Policies, §Foundation components, and
``docs/architecture/v2-roadmap.md`` Phase 4.
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are a senior software architect producing the **architecture \
document** for a single component in a software project. You will \
be given the component's metadata from the system-architecture \
pass (name, role paragraph, intended API), the top-level \
responsibilities assigned to it, its pre-minted \
subresponsibilities (which you will map to subcomponents below), \
the list of sibling components it may declare dependencies on, \
the public surfaces of any of those siblings that are already \
fully architected, the top-level policy candidates the system has \
minted so far, and optionally prior approved / pending drafts, \
user feedback, and parse-validate errors.

Your job is to produce a single ``<comparch>`` block containing \
seven sections in a fixed order: a role-level technical \
specification, the component's public surface, its private \
surface, the policies it mints locally, its external \
dependencies, its subcomponent decomposition, and the dependency \
edges between those subcomponents. The block is parsed and \
validated — structural errors are fed back to you on retry.

# Output format

Emit exactly one ``<comparch>`` block with these seven children \
in this order: ``<technical-specification>`` → \
``<public-surface>`` → ``<private-surface>`` → ``<policies>`` → \
``<dependencies>`` → ``<subcomponents>`` → ``<sub-dependencies>``. \
Example (abbreviated):

    <comparch>
      <technical-specification>
    Python 3.11 on FastAPI. PostgreSQL via SQLAlchemy. Session \
    tokens are opaque UUID4 strings stored in the database, not \
    JWTs — refresh is a server-side lookup, not a cryptographic \
    operation. Credential hashing uses bcrypt with a work factor \
    pinned in config.
      </technical-specification>
      <public-surface>
    The component exposes two call-sites to dependents:

    ```python
    def authenticate(credentials: Credentials) -> Session: ...
    def resolve_session(token: str) -> Principal | None: ...
    ```

    Plus an event emitted on state changes: \
    ``AuthenticationStateChanged(principal_id, kind)``.
      </public-surface>
      <private-surface>
    Internal helpers not visible to sibling dependents:

    ```python
    def _verify_password(raw: str, stored_hash: str) -> bool: ...
    def _rotate_stale_tokens(db: Session, cutoff: datetime) -> int: ...
    ```
      </private-surface>
      <policies>
        <policy>
          <name>Failed Login Rate Limiting</name>
          <trigger>any failed authentication attempt</trigger>
          <required>resp_ratelim01</required>
          <rationale>Brute-force attempts must bucket against \
    the same rate-limit sink every other protected endpoint uses. \
    Local to this component because the auth surface is where \
    failed attempts originate and the policy's <required> resp \
    has to be reachable from any site that can emit one.</rationale>
        </policy>
      </policies>
      <dependencies>
        <dep to="comp_audit999"/>
        <dep to="comp_foundati"/>
      </dependencies>
      <subcomponents>
        <subcomponent alias="session_store">
          <name>SessionStore</name>
          <role>Persist session state to the database and answer \
    lookups by token. Owns the sessions table and the token \
    rotation schedule.</role>
          <api-intent>create_session(principal_id) -> Session; \
    resolve(token) -> Session | None; rotate_expired() -> int. \
    No password material ever reaches this subcomponent.</api-intent>
          <responsibilities>
            <resp id="resp_sub_sess"/>
          </responsibilities>
        </subcomponent>
        <subcomponent alias="credential_gate">
          <name>CredentialGate</name>
          <role>Verify raw credentials against the stored hash \
    and produce a fresh session on success. The single site that \
    ever sees plaintext passwords.</role>
          <api-intent>verify(credentials) -> PrincipalId | None. \
    Delegates session creation to session_store.</api-intent>
          <responsibilities>
            <resp id="resp_sub_cred"/>
          </responsibilities>
        </subcomponent>
        <subcomponent alias="foundation">
          <name>Foundation</name>
          <role>Own this component's root folder: package init, \
    config loader, shared base types, logging setup.</role>
          <api-intent>load_settings(); configure_logging(); \
    AuthError base class.</api-intent>
          <responsibilities>
            <resp id="resp_sub_found"/>
          </responsibilities>
          <foundation/>
        </subcomponent>
      </subcomponents>
      <sub-dependencies>
        <dep from="session_store" to="foundation"/>
        <dep from="credential_gate" to="session_store"/>
        <dep from="credential_gate" to="foundation"/>
      </sub-dependencies>
    </comparch>

# Rules

## Structure

* Emit **exactly one** ``<comparch>`` root block. Nothing before, \
nothing after.
* The seven children **must appear in this order**: \
``<technical-specification>`` → ``<public-surface>`` → \
``<private-surface>`` → ``<policies>`` → ``<dependencies>`` → \
``<subcomponents>`` → ``<sub-dependencies>``. Out-of-order \
sections are a structural error.
* No unknown top-level children under ``<comparch>``.

## Fragment sections (techspec / pubapi / privapi)

* ``<technical-specification>`` is a **role-level** paragraph \
describing the component's technology and architecture choices. \
**No** per-subcomponent sequencing, no implementation walkthroughs. \
The techspec propagates downward only — it's what the \
subcomponent arch docs in Phase 5 will inherit and narrow, and \
it does not get regenerated when child impls iterate.
* ``<public-surface>`` is the API dependents see. Types, \
function signatures, method signatures, events. Code-shaped \
content lives in fenced code blocks; the parser does not \
inspect the code so any language is fine. Only surface that \
sibling components will call; internal helpers belong in \
``<private-surface>``.
* ``<private-surface>`` is internal types and helpers visible \
to this component's own subcomponents during their Phase 5 \
regen, but not to sibling dependents. Same fenced-code-block \
convention as the public surface.
* All three fragment sections must be non-empty. Do not put \
nested XML tags inside them — only prose and fenced code blocks.

## Policies

* ``<policies>`` is zero or more component-local ``<policy>`` \
entries. Each policy has exactly one ``<name>``, \
``<trigger>``, ``<required>``, and ``<rationale>`` child.
* ``<trigger>`` is a short semantic phrase identifying the sites \
the policy applies to (e.g. "any LLM call", "any failed \
authentication attempt", "any outbound HTTP request").
* ``<required>`` is a single ``resp_*`` ID. The allowed set is: \
(a) the top-level responsibilities assigned to this component, \
or (b) the pre-minted subresponsibilities this component owns. \
Cross-component resp references are not allowed — if a policy \
needs a resp that lives elsewhere, it's a top-level policy and \
belongs in the sysarch doc, not here.
* ``<rationale>`` is a paragraph explaining why the policy \
exists and why it's component-local rather than top-level. \
Carries weight in the policy application pass that runs after \
mint.
* If the component has no cross-cutting invariants worth \
stating, emit an empty ``<policies></policies>`` block.

## Dependencies (external)

* ``<dependencies>`` lists the sibling top-level components this \
component reaches for, each as ``<dep to="comp_XXXX"/>`` with a \
real ``comp_*`` ID (not an alias). The allowed targets are the \
sibling components listed in the input context — do not invent \
IDs, do not reference yourself.
* At most one ``<dep>`` per target; duplicates are rejected.
* This is external-only: deps between subcomponents live in \
``<sub-dependencies>``, not here.

## Subcomponents

* Each ``<subcomponent>`` carries an ``alias="..."`` attribute \
used for local references in ``<sub-dependencies>``. Alias \
syntax: lowercase letter first, then lowercase alphanumerics or \
underscores, 1-32 characters; regex \
``^[a-z][a-z0-9_]{0,31}$``. Aliases are unique within \
``<subcomponents>``.
* Each ``<subcomponent>`` has exactly one ``<name>``, one \
``<role>``, one ``<api-intent>``, and one ``<responsibilities>`` \
block. Subcomponents **inherit the kind** (domain / \
presentational) of the owning component and do NOT have their \
own ``<kind>`` tag — do not add one.
* ``<role>`` is a paragraph describing what the subcomponent \
does within this component. ``<api-intent>`` is a paragraph \
describing the shape of its intended API. Full public-surface \
detail comes later when Phase 5 generates the subcomponent's \
own arch doc.
* ``<responsibilities>`` contains one or more ``<resp \
id="resp_..."/>`` children. **Every resp ID must match one of \
this component's pre-minted subresponsibilities** shown in the \
input list, verbatim. No cross-component leaks, no invention, \
no renaming.
* **Every pre-minted subresponsibility in the input must be \
assigned to exactly one subcomponent** when the component is \
decomposed — orphans and duplicates are structural errors. \
Un-fanned-out is the only way to leave subresps unassigned \
(see next section).

## Un-fanned-out components

A component may legitimately choose **not** to decompose into \
subcomponents — especially small components that already fit in \
a single code territory. In that case:

* Emit ``<subcomponents></subcomponents>`` empty.
* Emit ``<sub-dependencies></sub-dependencies>`` empty.
* No foundation subcomponent is required.
* The pre-minted subresponsibilities from the input will be \
left unassigned at the subcomponent layer; Phase 6 will \
project them into a single ``impl_*`` leaf attached directly \
to this component instead.

Un-fanned-out is the right choice when a component's \
subresponsibilities are all tightly coupled to the same code \
territory and splitting them would create artificial seams. \
Decomposing is the right choice when the subresponsibilities \
genuinely describe distinct roles that want distinct code \
locations.

## Foundation subcomponent

* **If you decompose into subcomponents, exactly one must carry \
a self-closing ``<foundation/>`` marker.** This is the \
foundation subcomponent — it owns the component's root folder \
territory (package init, shared base types, config loader for \
the component's own config, cross-cutting utilities scoped to \
this component).
* Un-fanned-out components do NOT need a foundation child \
(there are no subcomponents at all).
* The foundation subcomponent is otherwise a normal \
subcomponent with its own name, role, api-intent, and at least \
one responsibility. The conventional default name is \
``Foundation`` unless the component has a more specific \
convention.

## Sub-dependencies

* ``<sub-dependencies>`` lists dependency edges between \
subcomponents within this component, each as \
``<dep from="ALIAS1" to="ALIAS2"/>`` with local aliases on \
both sides. Both aliases must be declared in ``<subcomponents>``.
* ``from`` and ``to`` must differ — self-dependencies are \
rejected.
* **The sub-dependency graph must be acyclic.** A cycle is a \
structural error that gets fed back on retry with the cycle \
path named.
* **Every non-foundation subcomponent must have a \
``<dep to="FOUNDATION_ALIAS"/>`` edge.** The foundation \
subcomponent owns the component's root folder territory and \
every other subcomponent's code reaches into it at runtime. \
This is enforced by the validator and mirrors the analogous \
rule for top-level components at the sysarch layer.

## Granularity

* Subcomponent count (when decomposing): typically 2 to 8 per \
component, including the foundation. Fewer than 2 usually \
means "un-fanned-out would be cleaner." More than 8 usually \
means you're reaching into implementation detail that belongs \
in the subcomponent's own Phase 5 arch doc or in individual \
``impl_*`` nodes.

## Meta-rules

* Do not include commentary about what you are doing or how you \
arrived at the decomposition. Output only the ``<comparch>`` \
block.
* Unescaped ``&`` and ``<`` inside fragment-section text (outside \
the XML tags themselves) are tolerated by the parser.
"""


def render_user_prompt(
    *,
    component_summary: str,
    parent_resps_summary: str,
    subresps_summary: str,
    sibling_comps_summary: str,
    dep_pubapi_summary: str,
    top_level_policy_candidates_summary: str,
    related_features_summary: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    parse_error: str | None = None,
    target_is_foundation: bool = False,
) -> str:
    """Build the user prompt for the comparch generator.

    All context sections are passed in as pre-formatted strings.
    The stage 2 ``regen_context`` helper produces them from the
    component's DB state; for unit tests they can be supplied
    directly.

    - ``component_summary``: component name + role + api-intent
      (the sysarch-time fragment content as context).
    - ``parent_resps_summary``: top-level resps assigned to this
      component via decomposition edges — context for reasoning
      about what policies might apply.
    - ``subresps_summary``: the pre-minted subresps this component
      owns. The LLM echoes their IDs into ``<responsibilities>``
      blocks inside ``<subcomponents>`` when decomposing.
    - ``sibling_comps_summary``: allowed targets for
      ``<dependencies>``. Each entry carries a stable ``comp_*``
      ID plus name + role for context.
    - ``dep_pubapi_summary``: public-surface fragments of any
      siblings that have already been architected (empty on
      first-run comparch since no other comps have run yet).
    - ``top_level_policy_candidates_summary``: the project's
      top-level policies. Informational — the application pass
      decides which apply to this component after mint, not
      here.
    - ``related_features_summary``: the features reachable via
      decomposition walk from this component's parent resps.
      Deep context for the LLM's understanding of what this
      component is *for*.
    - ``prior_approved`` / ``prior_pending`` / ``feedback`` /
      ``parse_error``: standard regen/retry context shared with
      every other bootstrap prompt.
    - ``target_is_foundation``: true when the component being
      architected is itself a foundation component (top-level or
      sub). Flips the "include a foundation subcomponent"
      invariant — foundations don't nest, so the decomposition
      must divide the foundation's territory exhaustively
      without a sub-foundation catch-all.
    """
    parts: list[str] = []
    if target_is_foundation:
        parts.append("# Foundation component (special case)")
        parts.append("")
        parts.append(
            "**This component is itself a foundation component.** "
            "Foundations do not nest: when you decompose a "
            "foundation, you must NOT include another foundation "
            "subcomponent in your `<subcomponents>` block. Instead, "
            "divide the foundation's territory **exhaustively** into "
            "concrete subcomponents that collectively own every "
            "file the foundation was responsible for. There is no "
            "residual catch-all at this level — the foundation "
            "itself already is the catch-all for its parent's level, "
            "and nesting another foundation inside it would "
            "double-count that role. If your decomposition would "
            "want a sub-foundation, that is the signal to either "
            "stay un-fanned-out (empty `<subcomponents>`) or reshape "
            "the decomposition so every concrete subcomponent "
            "claims a clearly-scoped slice of the territory."
        )
        parts.append("")
    parts.append("# Component")
    parts.append("")
    parts.append(component_summary.strip() or "(component details missing)")
    parts.append("")
    parts.append("# Top-level responsibilities assigned to this component")
    parts.append("")
    parts.append(parent_resps_summary.strip() or "(no responsibilities assigned)")
    parts.append("")
    parts.append("# Pre-minted subresponsibilities to assign to subcomponents")
    parts.append("")
    parts.append(subresps_summary.strip() or "(no subresponsibilities minted)")
    parts.append("")
    parts.append("# Sibling components (allowed <dependencies> targets)")
    parts.append("")
    parts.append(sibling_comps_summary.strip() or "(no siblings)")
    parts.append("")

    if dep_pubapi_summary and dep_pubapi_summary.strip():
        parts.append("# Dependency public surfaces")
        parts.append("")
        parts.append(
            "These are the public-surface fragments of sibling "
            "components you already depend on or may depend on. "
            "Use them to ground your own public-surface and "
            "technical-specification sections in the real shapes "
            "they expose."
        )
        parts.append("")
        parts.append(dep_pubapi_summary.strip())
        parts.append("")

    if related_features_summary and related_features_summary.strip():
        parts.append("# Related features")
        parts.append("")
        parts.append(
            "Features reachable via the decomposition walk from "
            "this component's top-level responsibilities. Deep "
            "context — you do not reference feature IDs directly, "
            "but you should know what user-visible work this "
            "component ultimately serves."
        )
        parts.append("")
        parts.append(related_features_summary.strip())
        parts.append("")

    if top_level_policy_candidates_summary and top_level_policy_candidates_summary.strip():
        parts.append("# Top-level policy candidates (informational)")
        parts.append("")
        parts.append(
            "These are the project's top-level policies. They are "
            "shown here so you can reason about whether your "
            "component's subresponsibilities already fulfill any of "
            "them — the application pass runs separately after "
            "this arch doc is approved. Do NOT reference these "
            "policy IDs in your own ``<policies>`` section; your "
            "``<policies>`` is only for component-local policies."
        )
        parts.append("")
        parts.append(top_level_policy_candidates_summary.strip())
        parts.append("")

    if prior_approved:
        parts.append("# Previously-approved architecture doc")
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
            "<comparch> block. The specific error was:"
        )
        parts.append("")
        parts.append(f"> {parse_error.strip()}")
        parts.append("")
        parts.append(
            "Fix the structure and re-emit the full <comparch> block. "
            "Preserve the architectural decisions where the feedback "
            "does not require a change — this retry is about format, "
            "not content."
        )
        parts.append("")

    parts.append("# Task")
    parts.append("")
    if parse_error:
        parts.append(
            "Re-emit the architecture doc as a valid <comparch> "
            "block addressing the structural error above. Output only "
            "the corrected <comparch> block."
        )
    elif feedback and (prior_pending or prior_approved):
        parts.append(
            "Revise the architecture doc to address the user feedback "
            "above. Preserve the decomposition where the feedback "
            "does not require a change. Output only the revised "
            "<comparch> block."
        )
    elif prior_pending or prior_approved:
        parts.append(
            "Regenerate the architecture doc from scratch based on "
            "the component context above. Output only the <comparch> "
            "block."
        )
    else:
        parts.append(
            "Write an initial architecture doc for this component "
            "based on its context above. Decide whether to decompose "
            "into subcomponents or stay un-fanned-out. Output only "
            "the <comparch> block."
        )

    return "\n".join(parts).rstrip() + "\n"
