"""Prompt template for the system-architecture (``sysarch_*``) draft.

The sysarch pass is the joint-reasoning step in the cold-start
chain. It takes the approved feature set and the approved
top-level responsibilities and produces the component graph:
top-level components (with role + API intent + assigned
responsibilities + optional foundation marker), top-level
policies, dependency edges, domain-parent edges, and a
system-level technical specification.

Output format (parsed by :mod:`backend.graph.parsers.xml_sections`
and validated by
:func:`backend.graph.parsers.validators.validate_sysarch`):

    <sysarch>
      <techspec>
        …project-level tech spec paragraph(s)…
      </techspec>
      <components>
        <component alias="billing">
          <name>Billing Service</name>
          <kind>domain</kind>
          <role>…role paragraph…</role>
          <api-intent>…api intent paragraph…</api-intent>
          <responsibilities>
            <resp id="resp_abc12345"/>
            <resp id="resp_def67890"/>
          </responsibilities>
        </component>
        <component alias="foundation">
          <name>Foundation</name>
          <kind>domain</kind>
          <role>…</role>
          <api-intent>…</api-intent>
          <responsibilities>…</responsibilities>
          <foundation/>
        </component>
        …
      </components>
      <policies>
        <policy>
          <name>Telemetry</name>
          <trigger>any LLM call</trigger>
          <required>resp_xyz00001</required>
          <rationale>…why this policy exists…</rationale>
        </policy>
        …
      </policies>
      <dependencies>
        <dep from="billing" to="foundation"/>
        …
      </dependencies>
      <domain-parent>
        <parent from="ui_billing" to="billing"/>
        …
      </domain-parent>
    </sysarch>

Section order is enforced. Dependencies use local alias
references; the mint handler translates them to real ``comp_*``
IDs at approval time. Policies reference ``resp_*`` IDs directly
(those IDs are already stable at sysarch generation time because
``reqs_*`` minted them before sysarch runs).

See ``docs/architecture/v2-rearchitecture.md`` §Generation order,
§Foundation components, §Policies, §Feature → Responsibility →
Component, and §Edge type vocabulary.
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are a senior software architect producing the **system \
architecture** for a software project. You will be given:

1. The approved feature list (each feature has a stable \
``feat_*`` ID).
2. The approved top-level responsibility list (each responsibility \
has a stable ``resp_*`` ID and a name + role paragraph).

Your job is to produce a single ``<sysarch>`` block containing \
five sections in a fixed order: a project-level technical \
specification, the top-level component list, top-level policies, \
dependency edges between components, and domain-parent edges \
(presentational → domain). The block is parsed and validated — \
structural errors are fed back to you on retry.

# Output format

Emit exactly one ``<sysarch>`` block with these five children in \
this order: ``<techspec>``, ``<components>``, ``<policies>``, \
``<dependencies>``, ``<domain-parent>``. Example:

    <sysarch>
      <techspec>
    Python 3.11 backend on FastAPI with a PostgreSQL primary \
store via SQLAlchemy. React 18 frontend built with Vite and \
React Query. Background jobs run on a custom lightweight queue. \
Anthropic Claude via the claude CLI is the only LLM surface; \
tokens are recorded in a telemetry side table on every call. \
All domain writes are event-sourced through a central reducer.
      </techspec>
      <components>
        <component alias="billing">
          <name>Billing Service</name>
          <kind>domain</kind>
          <role>Handle subscription state, payment collection, \
invoice generation and delivery, and account suspension on \
payment failure. Exposes a small internal API that other \
domains use to check billing status and a webhook endpoint for \
payment provider callbacks.</role>
          <api-intent>Internal REST + event hooks: \
``get_billing_state(account_id)``, \
``record_payment(account_id, amount, provider_ref)``, \
``BillingStateChanged`` event on transitions. Payment provider \
integration lives inside this component; other components only \
see the stable internal interface.</api-intent>
          <responsibilities>
            <resp id="resp_billing001"/>
            <resp id="resp_invoicing2"/>
          </responsibilities>
        </component>
        <component alias="auth">
          <name>Authentication</name>
          <kind>domain</kind>
          <role>Verify the identity of callers and establish \
session state that downstream components can read.</role>
          <api-intent>``authenticate(credentials) -> Session``, \
``resolve_session(token) -> Principal | None``. No password \
storage details exposed at this layer — those are internal.</api-intent>
          <responsibilities>
            <resp id="resp_auth00001"/>
          </responsibilities>
        </component>
        <component alias="foundation">
          <name>Foundation</name>
          <kind>domain</kind>
          <role>Own the project root: build config, package init, \
cross-cutting utilities, top-level entry point, env config \
loader, shared base types used by multiple subsystems. \
Everything that lives in the project's root folder and doesn't \
belong to any specific component lives here.</role>
          <api-intent>``load_settings()``, \
``configure_logging()``, shared base classes \
(``Handler``, ``Event``), and the main application factory \
other components import at startup.</api-intent>
          <responsibilities>
            <resp id="resp_config001"/>
          </responsibilities>
          <foundation/>
        </component>
      </components>
      <policies>
        <policy>
          <name>LLM Telemetry</name>
          <trigger>any LLM call</trigger>
          <required>resp_telemetry1</required>
          <rationale>Every LLM call must record its prompt \
tokens, completion tokens, and model to the telemetry side \
table so we can audit cost and latency. Without this, a \
regression in prompt length or a model change is invisible \
until the bill arrives.</rationale>
        </policy>
        <policy>
          <name>Event-Sourced Writes</name>
          <trigger>any domain write</trigger>
          <required>resp_reducer001</required>
          <rationale>Every mutation to domain state must go \
through the central reducer so the event log is the single \
source of truth. Direct ORM writes bypass replay and break \
rebuild-from-log.</rationale>
        </policy>
      </policies>
      <dependencies>
        <dep from="billing" to="auth"/>
        <dep from="billing" to="foundation"/>
        <dep from="auth" to="foundation"/>
      </dependencies>
      <domain-parent>
        <parent from="ui_billing" to="billing"/>
      </domain-parent>
    </sysarch>

# Rules

## Structure

* Emit **exactly one** ``<sysarch>`` root block. Nothing before, \
nothing after.
* The five children **must appear in this order**: \
``<techspec>`` → ``<components>`` → ``<policies>`` → \
``<dependencies>`` → ``<domain-parent>``. Out-of-order sections \
are a structural error.
* No unknown top-level children under ``<sysarch>``.

## Components

* Each ``<component>`` carries an ``alias="..."`` attribute used \
for local references within this doc. Alias syntax: lowercase \
letters, digits, and underscores; must start with a letter; 1 to \
32 characters; regex ``^[a-z][a-z0-9_]{0,31}$``. Aliases are \
unique within ``<components>`` — no two components may share one.
* Each ``<component>`` must contain exactly one ``<name>``, one \
``<kind>``, one ``<role>``, one ``<api-intent>``, and one \
``<responsibilities>`` block.
* ``<kind>`` is either ``domain`` or ``presentational``. Domain \
components do the structural work. Presentational components \
render views into domain content (UIs, dashboards, docs pages) \
and typically have a ``<domain-parent>`` edge pointing at the \
domain component they present.
* ``<name>`` is the human-readable display name — title case, \
short identifier. Different from the alias: ``alias="billing"``, \
``<name>Billing Service</name>``.
* ``<role>`` is a paragraph describing the component's role at \
role level. What it does, what scope it covers, what it does \
*not* cover. No implementation details, no specific technology \
choices — those belong in the system ``<techspec>`` or in the \
component's own arch doc (Phase 4).
* ``<api-intent>`` is a paragraph describing the shape of the \
API this component intends to expose. Enough detail for a \
dependent to know what calls to expect; not enough to be a full \
public-surface listing. Component arch docs (Phase 4) expand \
this into a real public-surface section.
* ``<responsibilities>`` contains one or more ``<resp \
id="resp_..."/>`` children. Each ``id`` must reference a \
top-level responsibility from the input list, verbatim. **Every \
top-level responsibility in the input must be assigned to \
exactly one component** — orphans and duplicates are \
structural errors.

## Foundation component

* **Exactly one component must carry a self-closing \
``<foundation/>`` marker as a child.** This is the foundation \
component — it owns the project's root folder files (build \
config, package init, shared utilities, entry point) and \
anything that doesn't logically belong to another top-level \
component. See the architecture doc §Foundation components for \
why this is required.
* The foundation component is otherwise a normal component — \
it has its own name, role, api-intent, and at least one \
responsibility. The conventional default name is ``Foundation`` \
unless the project has a more specific convention.

## Policies

* Top-level policies live under ``<policies>``. Zero or more are \
permitted; if the project has no cross-cutting invariants that \
need explicit statement, emit ``<policies></policies>`` empty.
* Each ``<policy>`` contains exactly one ``<name>``, one \
``<trigger>``, one ``<required>``, and one ``<rationale>``.
* ``<trigger>`` is a short semantic phrase identifying where the \
policy applies: ``any LLM call``, ``any domain write``, \
``any authenticated request handler``. Semantic, not structural \
— different projects phrase triggers differently.
* ``<required>`` is a bare ``resp_*`` ID referencing the \
responsibility that must be fulfilled at every trigger site. \
The ID must be in the input top-level responsibility list.
* ``<rationale>`` is a paragraph explaining why the policy \
exists. Carries real weight — the LLM applying policies later \
reads this to decide which components the policy actually \
applies to.

## Dependencies

* Each ``<dep from="..." to="..."/>`` uses local aliases on \
both sides. Both aliases must be declared in ``<components>``.
* ``from`` and ``to`` must differ — self-dependencies are \
rejected.
* **The dependency graph must be acyclic.** A cycle is a \
structural error that gets fed back on retry with the cycle \
path named.
* Foundation should typically be a *sink* (everything depends \
on it, it depends on nothing). It's fine for it to have no \
dependencies.
* Policies can induce dependency edges — if a policy says "any \
LLM call must fulfill ``resp_telemetry``," every component that \
has LLM-calling responsibilities needs a dep on whichever \
component fulfills ``resp_telemetry``. Reason about policies \
first, then emit ``<dependencies>`` so policy-induced deps \
land naturally. This is why the section order puts \
``<policies>`` before ``<dependencies>``.

## Domain-parent

* Each ``<parent from="..." to="..."/>`` is a presentational → \
domain edge. The ``from`` alias must belong to a component with \
``<kind>presentational</kind>``; the ``to`` alias must belong \
to a domain component.
* A presentational component may have zero or more domain \
parents. Domain components may be referenced by multiple \
presentationals.

## Granularity and coverage

* Top-level component count: typically 5 to 15 for a normal \
project, not counting the foundation. If you're at 3, you're \
probably glossing over decomposition; if you're at 25, you're \
reaching into subcomponent territory that belongs in Phase 4 \
component arch docs.
* Every top-level responsibility from the input list must be \
assigned to exactly one component's ``<responsibilities>`` \
block. Missing assignments are a structural error.

## Meta-rules

* Do not include commentary about what you are doing or how you \
arrived at the list. Output only the ``<sysarch>`` block.
* Unescaped ``&`` and ``<`` inside ``<role>`` / ``<api-intent>`` / \
``<techspec>`` / ``<rationale>`` text are fine — the parser \
tolerates them.
"""


def render_user_prompt(
    *,
    features_summary: str,
    reqs_summary: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    parse_error: str | None = None,
) -> str:
    """Build the user prompt for the sysarch generator.

    ``features_summary`` and ``reqs_summary`` are caller-supplied
    markdown renderings of the approved features and top-level
    responsibilities. Both must carry IDs verbatim — the LLM
    echoes them back in ``<responsibilities>`` and ``<required>``
    blocks.

    The remaining parameters mirror the feature-expansion and
    requirements prompts: prior approved / pending for regen
    iteration, user feedback for revision, and ``parse_error``
    for the parse-validate retry path.
    """
    parts: list[str] = []
    parts.append("# Project features (approved upstream)")
    parts.append("")
    parts.append(features_summary.strip() or "(no features minted yet)")
    parts.append("")
    parts.append("# Top-level responsibilities (approved upstream)")
    parts.append("")
    parts.append(reqs_summary.strip() or "(no responsibilities minted yet)")
    parts.append("")

    if prior_approved:
        parts.append("# Previously-approved system architecture")
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
            "<sysarch> block. The specific error was:"
        )
        parts.append("")
        parts.append(f"> {parse_error.strip()}")
        parts.append("")
        parts.append(
            "Fix the structure and re-emit the full <sysarch> block. "
            "Preserve the component + policy + edge set where the "
            "feedback does not require a change — this retry is about "
            "format, not content."
        )
        parts.append("")

    parts.append("# Task")
    parts.append("")
    if parse_error:
        parts.append(
            "Re-emit the system architecture as a valid <sysarch> "
            "block addressing the structural error above. Output only "
            "the corrected <sysarch> block."
        )
    elif feedback and (prior_pending or prior_approved):
        parts.append(
            "Revise the system architecture to address the user "
            "feedback above. Preserve the component + policy + edge "
            "set where the feedback does not require a change. Output "
            "only the revised <sysarch> block."
        )
    elif prior_pending or prior_approved:
        parts.append(
            "Regenerate the system architecture from scratch based on "
            "the features and responsibilities above. Output only the "
            "<sysarch> block."
        )
    else:
        parts.append(
            "Write an initial system architecture for this project "
            "based on the features and responsibilities above. Output "
            "only the <sysarch> block."
        )

    return "\n".join(parts).rstrip() + "\n"


def format_reqs_summary(resps: list[dict]) -> str:
    """Render top-level ``resp_*`` nodes as prompt-ready markdown.

    Each entry must carry ``id``, ``name``, ``content`` (the intent
    paragraph). The rendered list has IDs rendered prominently so
    the LLM echoes them verbatim into ``<responsibilities>`` and
    ``<required>`` blocks. Ordered by the input list — the caller
    is expected to pass resps in display order.
    """
    if not resps:
        return "(no responsibilities minted yet)"
    lines: list[str] = []
    for resp in resps:
        rid = resp.get("id", "").strip() or "(unknown-id)"
        name = resp.get("name", "").strip() or "(unnamed)"
        intent = (resp.get("content") or "").strip()
        lines.append(f"- `{rid}` **{name}**: {intent}")
    return "\n".join(lines)
