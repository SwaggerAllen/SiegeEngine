"""Prompt template for the system-architecture (``sysarch_*``) draft.

The sysarch pass is the joint-reasoning step in the cold-start
chain. It takes the approved feature set and the approved
top-level responsibilities and produces the component graph:
top-level components (with micro-fields: purpose, owned-invariants,
primary-operations + assigned responsibilities + optional foundation
marker), top-level policies, dependency edges, domain-parent edges,
and a system-level technical specification structured into labeled
blocks.

Output format (parsed by :mod:`backend.graph.parsers.xml_sections`
and validated by
:func:`backend.graph.parsers.validators.validate_sysarch`):

    <sysarch>
      <techspec>
        <runtime>…language + runtime + process model…</runtime>
        <persistence>…storage pattern + schema approach…</persistence>
        <write-path>…event sourcing / direct mutations / CQRS…</write-path>
        <concurrency>…single-threaded / async / workers / locks…</concurrency>
        <testing>…test pyramid + frameworks…</testing>
        <deploy>…build + deployment shape…</deploy>
        <technologies>…verbatim concrete choices from the input…</technologies>
      </techspec>
      <components>
        <component alias="billing">
          <name>Billing Service</name>
          <kind>domain</kind>
          <purpose>…one sentence, why this component exists.…</purpose>
          <owned-invariants>
            <invariant>…short noun phrase…</invariant>
            <invariant>…</invariant>
          </owned-invariants>
          <primary-operations>
            <operation>…short verb phrase…</operation>
            <operation>…</operation>
            <operation>…</operation>
          </primary-operations>
          <responsibilities>
            <resp id="resp_abc12345"/>
            <resp id="resp_def67890"/>
          </responsibilities>
        </component>
        <component alias="foundation">
          <name>Foundation</name>
          <kind>domain</kind>
          <purpose>…</purpose>
          <owned-invariants>…</owned-invariants>
          <primary-operations>…</primary-operations>
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

from backend.graph.prompts._prior_framing import (
    render_prior_framing_section,
    render_prior_review_section,
    split_prior_introduction,
)

_SYSTEM_PROMPT_TEMPLATE = """\
You are producing the **system architecture** for a software \
project. The entire downstream generation chain — \
subrequirements, component architecture, individual \
implementation plans — will read your output as the compressed \
description of this project and will not re-read the feature \
list or the input document. Your job is not to write a complete \
specification. It is to articulate **handles** — short, \
specific, project-distinctive component names and paragraphs — \
that downstream passes can reason from directly. A vague handle \
at this layer forces every later pass to guess, and a guess \
here gets multiplied across every tier below. There is **no \
target component count** — emit as many components as the \
project's data-ownership and failure-mode boundaries warrant, \
and no fewer. Conserving components by merging unrelated \
concerns produces a vague handle at the merged component just \
as surely as splitting one coherent concern across two \
components produces a vague handle at each. Prefer concrete \
language ("settles card charges through the provider gateway") \
to category labels ("handles payments"). A component name that \
could plausibly belong to any SaaS project is probably too \
generic.

You will be given:

1. The approved feature list (each feature has a stable \
``feat_*`` ID).
2. The approved top-level responsibility list (each responsibility \
has a stable ``resp_*`` ID and a name + role paragraph).
3. The project input document, which carries the original \
framing and character.

Your output is a single ``<sysarch>`` block containing five \
sections in a fixed order: a project-level technical \
specification, the top-level component list, top-level policies, \
dependency edges between components, and domain-parent edges \
(presentational → domain). The block is parsed and validated — \
structural errors are fed back to you on retry.

# Output format

Emit two top-level blocks in this order: ``<introduction>`` \
and ``<sysarch>``. The ``<introduction>`` is required — a \
2–5 paragraph prose preamble that captures your initial \
thinking before the structured output: how you read the \
responsibility set into component boundaries, which tensions \
or tradeoffs the input makes visible, which alternative cuts \
you considered and rejected. Downstream tiers don't read this \
intro, but when sysarch regenerates with feedback you (or a \
later model) can refer back to it to stay anchored in your \
initial framing instead of restarting from scratch.

After ``<introduction>``, emit exactly one ``<sysarch>`` block \
with these five children in this order: ``<techspec>``, \
``<components>``, ``<policies>``, ``<dependencies>``, \
``<domain-parent>``. Example:

    <introduction>
      The responsibility set cleanly partitions into three \
    top-level cuts: identity + authorization, billing + payment \
    lifecycle, and notification delivery. I kept the \
    domain/presentational split narrow — only Billing has a \
    presentational counterpart (the customer-facing invoices \
    view); auth and notifications are purely internal.

      Tradeoffs worth flagging on regen: I considered folding \
    notifications into Billing since most notifications are \
    payment-triggered, but kept it separate because the project \
    doc implies non-billing notifications (support responses) \
    are coming. Also went with Postgres + event sourcing on the \
    Billing side for audit reasons.
    </introduction>
    <sysarch>
      <techspec>
        <runtime>{Pick the language and runtime that fit the \
project's constraints — e.g., a typed compiled language for a \
performance-critical data plane, an actor-based VM for \
high-concurrency message routing, a managed runtime for a \
forms-heavy admin app. Name the version pin and the process \
shape (per-environment, per-tenant, sidecar pattern, \
serverless).}</runtime>
        <persistence>{Name the durable store and the schema \
shape. Be specific about whether ownership is per-component \
(each comp has its own tables / namespace) or shared, and how \
identity flows (typed IDs, UUIDs, scoped foreign keys). Mention \
any caching layer + invalidation rule.}</persistence>
        <write-path>{Describe how mutations land. Single \
event-sourced reducer? Direct ORM writes? Outbox pattern with \
async projection? CQRS split with read replicas? Whatever the \
shape, name it specifically — downstream impl tiers read this \
to decide handler patterns.}</write-path>
        <concurrency>{Concurrency model + isolation boundaries. \
Examples: "supervised actor trees per project; long-running \
external calls isolated in their own supervisor", "async \
event loop with bounded worker pool for blocking I/O", \
"per-request goroutines with channels for fan-out". Be \
specific enough that impl can pick libraries from this.}</concurrency>
        <testing>{Test strategy that downstream tiers will \
follow. Unit coverage approach, integration harness shape, \
property-based testing for invariants, full-chain drain harness, \
etc.}</testing>
        <deploy>{Build + deploy shape. Container image, binary, \
function bundle. Hosting target (your cloud / on-prem / \
self-hosted). Runtime topology (single-process, multi-replica, \
horizontally-scaled).}</deploy>
        <technologies>{Comma-separated short list of the load- \
bearing tech choices — language + framework + persistence + \
deploy + any other choice impl needs to know about. Be specific \
to your project; this list anchors every comparch + impl tier \
that follows.}</technologies>
      </techspec>
      <components>
        <component alias="billing">
          <name>Billing Service</name>
          <kind>domain</kind>
          <purpose>Owns the subscription and payment lifecycle \
for every account.</purpose>
          <owned-invariants>
            <invariant>exactly one active subscription per account</invariant>
            <invariant>every charge traces to an invoice row</invariant>
            <invariant>grace-period expiry suspends access atomically</invariant>
          </owned-invariants>
          <primary-operations>
            <operation>fetch the current billing state for an account</operation>
            <operation>record a payment attempt and its outcome</operation>
            <operation>emit a subscription-changed event on transitions</operation>
            <operation>reconcile webhook callbacks from the payment provider</operation>
          </primary-operations>
          <responsibilities>
            <resp id="resp_billing001"/>
            <resp id="resp_invoicing2"/>
          </responsibilities>
        </component>
        <component alias="auth">
          <name>Authentication</name>
          <kind>domain</kind>
          <purpose>Verifies the identity of callers and issues \
session state downstream components can trust.</purpose>
          <owned-invariants>
            <invariant>every active session maps to one account</invariant>
            <invariant>credentials are hashed at rest</invariant>
          </owned-invariants>
          <primary-operations>
            <operation>authenticate credentials into a session</operation>
            <operation>resolve a session token into a principal</operation>
            <operation>revoke an active session on demand</operation>
          </primary-operations>
          <responsibilities>
            <resp id="resp_auth00001"/>
          </responsibilities>
        </component>
        <component alias="foundation">
          <name>Foundation</name>
          <kind>domain</kind>
          <purpose>Owns the project root: shared utilities, the \
entry point, the env config loader, and shared base types.</purpose>
          <owned-invariants>
            <invariant>a single source of truth for app settings</invariant>
            <invariant>shared handler/event base types stay versioned together</invariant>
          </owned-invariants>
          <primary-operations>
            <operation>load settings from the environment</operation>
            <operation>configure logging for the whole app</operation>
            <operation>expose the application factory to startup</operation>
          </primary-operations>
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

## Techspec

* ``<techspec>`` is the project-level technical specification, \
structured into seven fixed labeled blocks in order: \
``<runtime>`` → ``<persistence>`` → ``<write-path>`` → \
``<concurrency>`` → ``<testing>`` → ``<deploy>`` → \
``<technologies>``. Each block is **1-2 short sentences** (one \
sentence is fine when the call is unambiguous). No free prose \
outside the labeled blocks; no nested tags inside them; no \
reordering. The comparch pass reads each block back verbatim \
when deciding internal component structure.
* ``<runtime>`` — language + language version + process model \
(single-process async loop / multi-process worker / BEAM actor \
tree, etc).
* ``<persistence>`` — storage engine + schema approach (relational \
with per-entity tables / document store with typed keys / \
hybrid).
* ``<write-path>`` — the write pattern that every downstream \
component must honour: direct ORM writes / event-sourced \
reducer / command-handler split / CQRS, etc.
* ``<concurrency>`` — concurrency model and how long-lived work \
is isolated: single-threaded / async I/O / worker pool / \
dedicated process per tenant.
* ``<testing>`` — test pyramid shape + frameworks (pytest + \
integration drain / Jest + Playwright / ExUnit + property \
tests).
* ``<deploy>`` — build + deployment shape (Docker image on CI / \
single Fly.io container / Kubernetes + Helm / static site + \
edge functions).
* ``<technologies>`` — verbatim list of concrete framework / \
library / service choices named in the input document. This \
block exists because the upstream tiers strip the input's \
technology decisions during extraction and compression; if you \
don't record them here they are lost. Comma-separated, \
normalized casing, one line. Do **not** invent technologies \
that the input didn't name — this is a record of the input's \
choices, not a recommendation.
* Prefer the **pattern** in each narrative block, not just the \
ingredient. "Python 3.11" is underspecified; "Python 3.11 FastAPI \
process per environment; single-process async event loop fronts \
the API" is a real handle.
* If the project has architectural non-negotiables (all writes \
event-sourced; all LLM calls logged; no direct DB access \
outside the reducer), name them inside the relevant block. \
``<write-path>`` is the usual home for reducer / event-log \
invariants.
* **If the project commits to a typed error discipline, name \
it explicitly.** Languages whose ecosystems use typed error \
returns (Elixir tagged tuples, Rust ``Result``, TypeScript \
discriminated unions, Go's typed errors) benefit from \
project-wide commitment because the type system becomes the \
cross-section consistency anchor at lower tiers. Comparch \
will read this and produce public-surface return types whose \
error variants line up with each component's failure-surface \
entries; if the techspec doesn't name the discipline, comparch \
falls back to ad-hoc choices and the consistency anchor is \
lost. ``<runtime>`` or ``<write-path>`` is the usual home for \
this commitment ("error handling uses tagged tuples \
throughout — no exceptions cross component boundaries"). Skip \
this bullet for languages without an idiomatic typed-error \
discipline (vanilla Python, Ruby, JavaScript without \
discriminated unions); ad-hoc exception handling is the \
default there and that's fine.

## Components

* Each ``<component>`` carries an ``alias="..."`` attribute used \
for local references within this doc. Alias syntax: lowercase \
letters, digits, and underscores; must start with a letter; 1 to \
32 characters; regex ``^[a-z][a-z0-9_]{0,31}$``. Aliases are \
unique within ``<components>`` — no two components may share one.
* Each ``<component>`` must contain exactly one ``<name>``, one \
``<kind>``, one ``<purpose>``, one ``<owned-invariants>``, \
one ``<primary-operations>``, and one ``<responsibilities>`` block. \
There is no ``<failure-surface>`` at this tier — the comparch pass \
writes a sharper, component-local failure surface once it has the \
full techspec + pubapi + invariants in hand.
* ``<kind>`` is either ``domain`` or ``presentational``. **The \
split is external-interface vs. domain-logic, not \
backend-vs-frontend.** Domain components own state, business \
logic, mutations, and the wrapper machinery for services *we* \
call outbound (LLM provider client, git forge client, IdP \
verification client — those are things we consume, not \
surfaces for outsiders to access us through). Presentational \
components are **external interfaces**: surfaces through which \
parties *outside our trust boundary* interact with the system. \
That includes humans via UIs / CLIs / operator consoles, but \
also services via REST / GraphQL / gRPC, subscribers via \
webhooks / SSE streams, and users via notification channels \
(email, in-app, team messaging). Classifying by \
external-interface role, not by "does a browser render it," \
means a notification dispatcher is presentational (it exposes \
our events to outside subscribers), a REST API surface is \
presentational (external services consume our projection \
through it), and a webhook relay is presentational (external \
subscribers receive our events through it). **Decision test:** \
if you deleted this component, would the system lose *state or \
business logic* (→ domain) or lose a *way to expose state/events \
to outsiders* (→ presentational)? Outbound-call wrappers like \
LLM Gateway and Git Forge fail this test in the domain \
direction — deleting them breaks our ability to *use* external \
services, not an outside party's ability to access us.
* **A presentational component is one coherent consumer \
interaction, not one audience.** The unit of decomposition is \
"what the consumer is trying to do through this surface", not \
"who is on the other end". For UI presentationals the \
consumer is a human and the "task" is their interaction \
pattern (review an artifact, navigate the graph, triage the \
queue). For non-UI presentationals the consumer is another \
service or subscriber and the "task" is their interaction \
pattern too (query the projection via REST, receive review \
events via webhook, get notifications for assigned reviews). \
Two distinct interactions become two presentational \
components even when the same consumer performs both; one \
interaction stays one component even when multiple consumer \
types hit it. A single presentational that covers "everything \
an admin sees" or "every REST endpoint" is an *application*, \
not a slice, and it will pull in too many domains and \
generate with too little specificity.
* **Presentationals own interface concerns, not domain-logic \
concerns.** This is the most common failure mode at this tier \
and the easiest one to fall into: the LLM, asked "what does \
this interface component own?", parrots the domain parent's \
invariants and operations back. It doesn't. The *domain* owns \
business invariants ("exactly one active subscription per \
account", "credentials are hashed at rest") and business \
operations ("record a payment", "revoke a session"). The \
*presentational* owns whatever is specific to the **consumer \
interface**: for a UI that's rendering (what's visible, how \
transitions animate), interaction (gestures, input validation, \
concurrent-action serialization), and UI-local state \
(selection, drafts, navigation history); for a REST / GraphQL \
API that's schema shape, versioning, idempotency headers, \
pagination, per-token rate limiting, and routing writes \
through the reducer; for a webhook relay that's delivery \
semantics (at-least-once, retry backoff), payload signing, \
event-type filtering, and subscriber registration; for a \
notification dispatcher that's channel routing, per-user \
preferences, batching granularity, and delivery semantics. \
When you write a presentational's ``<purpose>``, \
``<owned-invariants>``, and ``<primary-operations>``, the \
subject is the interface's contract with its consumers, not \
the backend's contract with itself. Compare (UI case):
  * Wrong (parrots the domain): purpose "owns the subscription \
    and payment lifecycle", invariants "exactly one active \
    subscription per account", operations "record a payment".
  * Right (UI interface): purpose "lets a customer review and \
    edit their subscription", invariants "displayed price \
    always matches the backend's current state", "one edit \
    session per customer at a time", operations "render the \
    current subscription", "submit a plan change for \
    confirmation", "cancel an in-flight edit".
  Compare (REST API case):
  * Wrong (parrots the domain): purpose "owns the projection", \
    invariants "all writes flow through the reducer", \
    operations "validate events", "apply projection deltas".
  * Right (REST interface): purpose "exposes the projection as \
    a versioned REST surface for external consumers", \
    invariants "every endpoint returns JSON conforming to the \
    documented schema", "write endpoints route through the \
    reducer without bypass", "rate limits applied per API \
    token", operations "serve a projection read with \
    pagination", "accept a write request and forward to the \
    reducer", "reject unauthorized calls with a documented \
    error code".
* If a presentational's ``<owned-invariants>`` or \
``<primary-operations>`` are identical to its domain parent's, \
that is a signal you are re-describing the domain instead of \
articulating the interface. Rewrite them to name \
interface-level concerns (rendering, API shape, delivery \
semantics, consumer-facing contract). An honest empty edge \
case is better than a duplicated invariant — if the interface \
genuinely has no concerns beyond "mirror the domain", list \
the interface-specific ones you *do* have (stale-state \
handling, schema versioning, optimistic updates, retry \
semantics) and move on.
* **Watch for ownership vocabulary leaking into a \
presentational component.** Words like "persist", "atomically", \
"commit", "transaction", "stored", "validated and committed", \
"event log", "consistency", "concurrent write" are \
*ownership* vocabulary — they describe the domain's contract \
with itself. Delivery-format vocabulary (REST, HTTP, JSON, \
SSE, webhook, email) is fine on an interface presentational \
because it's describing the interface's own contract with \
consumers. If any ownership word appears in a presentational \
component's ``<owned-invariants>`` or ``<primary-operations>``, \
you are describing the backend's contract instead of the \
interface's own contract and the invariant belongs on the \
domain parent. Apply this self-check to each presentational \
invariant: rewrite it to name an *interface* concern \
(rendering for UI, schema shape for API, delivery semantics \
for webhook/notification), OR move it to the domain parent \
and replace it on the presentational with a real interface \
invariant. Concrete example: "owner assignment captures \
persist atomically with the fan-out approval" is a backend \
ownership invariant; \
the UI version is "owner-assignment input renders inline with \
the fan-out approval gate so the user assigns owners in the \
same submit action." Same underlying concern; one is what the \
reducer guarantees, the other is what the UI presents.
* **Each presentational component has 1 or 2 domain parents. \
More than 2 is a structural error.** If the component's work \
spans three or more domains, the task isn't one task — split \
it. The 1–2 cap is enforced by the validator; a document that \
wires 3+ ``<parent>`` edges from one presentational alias will \
be rejected with an error pointing at the offending component. \
If two domain parents expose fundamentally different handle \
shapes (different entity types, different operations), that's \
itself a signal the presentational is combining two tasks \
rather than surfacing one.
* **Anti-patterns that indicate you're building an application \
instead of a slice:** for UI presentationals, names ending in \
``Workspace``, ``Dashboard``, ``Console``, ``UI``, or ``Hub``; \
for API / event-stream / webhook / notification \
presentationals, names like ``Service``, ``Gateway``, \
``Facade``, or generic suffixes that could describe any \
external-interface component (``ApiSurface``, \
``EventRelay``). Purposes that describe a collection of \
interactions ("renders the graph and the review panels and \
the chat"; "serves every projection read endpoint and all \
write endpoints and rate-limits them") rather than a single \
coherent consumer interaction. 3+ domain parents. If your \
first draft of the presentational layer has one component per \
audience (or one per protocol — a catch-all ``RestSurface`` \
covering every endpoint), start over and slice by interaction \
instead.
* **Domain-presentational pairing is the expected default, not \
a carve-out.** Almost every project has at least one external \
consumer (humans, services, subscribers), so almost every \
project has at least one presentational component. A system \
with zero presentational components is the exception — it \
implies the system has no external interface, which is rare. \
For every *interaction* an outside party performs against \
what the domains expose, expect a presentational component \
with one or two ``<domain-parent>`` edges to the domains that \
task actually touches. One domain may be presented by multiple \
presentationals (the same billing domain surfaces through a \
subscription-management task and a payment-history task — \
those are two components). One presentational surfaces one or \
two domains; if you find yourself listing three, the task is \
too broad.
* Every presentational component's ``<purpose>`` is a \
one-sentence statement of the **consumer interaction** it \
serves. For UI presentationals that's a user task ("Lets a \
reviewer work through their outstanding review queue one \
artifact at a time."); for non-UI presentationals it's an \
interface contract ("Exposes the projection read set as a \
versioned REST surface for external services.", "Pushes \
review-lifecycle events to registered webhook subscribers \
with cryptographically-signed payloads.", "Delivers \
notifications to configured channels per user preference."). \
If that sentence covers multiple unrelated interactions, the \
component is too big. The purpose is load-bearing: the \
downstream comparch pass reads it as the primary handle for \
what to decompose into, and an interaction-shaped purpose \
keeps the decomposition focused on that interface's contract \
rather than on a grab-bag of endpoints or channels.
* A responsibility may appear in one presentational \
component's ``<responsibilities>`` block **in addition to** its \
owning domain component — and for any responsibility that has \
an external-facing face (UI, REST, webhook, notification, \
etc.), it **should**. This mirror pattern is how sysarch \
expresses "the presentational component exposes this \
responsibility to outside consumers." The reqs tier \
deliberately does not split responsibilities into domain-side \
and interface-side halves — one responsibility like "Payment \
Collection" covers both the backend mechanics and whatever \
surface presents it (UI, REST, both) — and it is the sysarch \
layer's job to decide which side(s) claim each resp. When the \
presentational claims a resp via the mirror, subreqs later \
rotates it to interface-shaped articulation; the \
presentational's comparch inherits the domain's pubapi via \
the ``<domain-parent>`` edge. Without the mirror, the subreqs \
pass for the presentational has no parent resps to decompose.
* Concretely: if a presentational component has a \
``<domain-parent>`` edge to a domain component, every \
responsibility on that domain that the presentational actually \
surfaces should be mirrored into the presentational's \
``<responsibilities>`` block. Presentationals whose \
``<responsibilities>`` blocks are empty or far smaller than \
the set of resps they ought to surface are under-specified — \
they give the subreqs pass nothing to rotate, and their \
comparch pulls in domain pubapi without having decomposed its \
own interface-side articulation.
* **If the project has significant shared interface \
infrastructure**, consider whether a top-level presentational \
component should own that shared code so other presentational \
components can depend on it. For UI presentationals this is \
the routing / theming / state-management / layout-shell tier \
(Phoenix LiveView shell, Next.js app shell). For non-UI \
presentationals this is things like a shared REST-gateway \
layer handling auth / rate limiting / observability \
middleware that every endpoint-shaped presentational mounts \
inside. Either way this is the presentational counterpart to \
the foundation component — not marked ``<foundation/>`` \
(there's only one of those), but serving an analogous role as \
the shared-infrastructure dep target for the presentational \
side of the tree.
* **Admin, operator, and debugging surfaces are first-class \
presentationals — generate one per distinct admin/operator \
interaction.** A common failure mode is to generate \
presentationals only for the primary user-facing flows \
(reviewing artifacts, navigating the graph, triaging the \
review queue) and skip the surfaces operators and admins \
need. These are real presentationals even when their \
interaction model is mostly *browse + filter + occasional \
edit form*. For every domain component that exposes \
admin-managed state (bundles, credentials, scoped roles, \
audit log, scheduler health, token usage), there is an \
admin-side presentational whose interaction is "operator \
inspects and adjusts that state". For every domain that \
emits audit-worthy events (event spine, permission resolver, \
credential vault), there is a browser-side presentational \
whose interaction is "operator scans the trail to answer \
*what happened*". For every long-running background system \
(scheduler, flow executor, generation pipeline), there is a \
debugging-side presentational whose interaction is \
"operator inspects current state to diagnose stuck or \
unexpected behavior". Concrete examples this prompt has \
seen omitted from clean-slate generation: a bundle library \
curator (browse instance bundles + import/approve), an \
ownership / role binding editor (browse the binding map + \
delegate / transfer), a credential & token usage monitor \
(scoped credential metadata + per-tier usage rollups), an \
audit trail browser (filter the immutable log by actor / \
action / time), a scheduler state viewer (per-node blocking \
reason + queue concurrency utilization), a code diff \
inspector (file-level diffs scoped to declared territory + \
CI status), a team artifact discussion thread (threaded \
team-side conversation distinct from private AI chat). Don't \
skip these because their owned-invariants feel thinner than \
the user-facing presentationals' — "displayed values reflect \
projection state within one PubSub cycle", "filter results \
reflect the append-only audit log without summarization", \
"binding editor reflects updated assignments immediately \
after submission" are real interface-side invariants that \
admin/operator/debugging surfaces own. A sysarch with \
domain-side admin/audit/debugging components but no \
matching presentationals is under-specified — it gives \
those domains nothing to surface to operators.
* ``<name>`` is the human-readable display name — title case, \
short identifier. Different from the alias: ``alias="billing"``, \
``<name>Billing Service</name>``. **Name components \
project-specifically, not generically.** If two unrelated \
projects could plausibly have a component with this name, it \
is too generic. Prefer the most distinguishing aspect of what \
this component does over the category it sits in: \
"Subscription Lifecycle" beats "Billing Service"; "Credential \
Broker" beats "Authentication"; "Bundle Resolver" beats \
"Configuration Management". The name is the shortest handle \
in the system — it has to earn its brevity by being specific.
* ``<purpose>`` is the one-sentence reason this component \
exists. The subrequirements pass (decomposing this component \
into subresponsibilities) and the comparch pass (choosing its \
internal subcomponent decomposition) both read it first. Name \
the component-distinctive *why* — the specific territory it \
owns — not the category it sits in. "Handles authentication" \
is category-speak; "verifies the identity of callers and \
issues session state downstream components can trust" is a \
handle. Do not cram multiple concerns into the sentence; if \
you need an ``and``, consider whether the component is \
actually two.
* **The purpose names a distinctive substance, not a bucket.** \
After one read, a downstream reader should be able to repeat \
back what this component *is* in their own words. "Guards \
the platform-level ref tier — the universal escape hatch for \
supplemental reference content that doesn't fit bundle-\
declared tier hierarchy" reads as substance: there's a \
specific piece of platform machinery it owns. "Owns reference \
content management" reads as a bucket: a label that could \
collect anything tangentially related. Components whose \
purpose reads as a bucket produce subcomponents that feel \
like buckets too — and at comparch the consequence is \
contradictions, because the model has no crisp mental model \
of what each section is *about*. The fix: name the specific \
thing the component owns that nothing else in the system \
owns.
* ``<owned-invariants>`` lists **2-4 short noun phrases** \
naming the durable state or guarantees this component owns. \
Each invariant is a contract that downstream comparch and \
impl passes must preserve; together they answer "what is this \
component *for*, structurally?". Examples: "exactly one active \
subscription per account", "every charge traces to an invoice \
row", "credentials are hashed at rest". Avoid impact \
categories ("must be reliable") — an invariant must be \
specific enough that a reviewer can point at a concrete \
implementation and say yes/no. If you find yourself listing \
more than four, some of them are actually sub-component \
concerns — push them down to comparch. If you find yourself \
listing fewer than two, the component's role is too thin.
* **Phrase invariants as structural facts, not procedural \
promises.** Structural phrasing names a property of the \
state, the call graph, or the data shape — "X is the only \
path to Y", "Y is a deterministic function of X", "Z is \
committed before W is dispatched", "exactly one active X per \
Y", "every X carries Z". Procedural phrasing names a verb \
the system performs every time — "every X does Y", "X always \
succeeds", "no X ever fails". Procedural phrasing invites \
the comparch and impl tiers to write contradicting failure \
surfaces (the failure surface inevitably says "X did not do \
Y" or "X failed"); structural phrasing lets downstream tiers \
describe coverage gaps and residual risks consistently \
without contradicting the invariant. This rule propagates \
downward — comparch will inherit your framing for its own \
subcomponent invariants, and impl reads both. If you find \
yourself starting an invariant with "every" or "always", \
look for the structural rephrase: what fact about the \
schema, the call graph, or the data does that statement \
encode?
* ``<primary-operations>`` lists **3-6 short verb phrases** \
naming the operations callers invoke on this component. Each \
is a one-line handle: "authenticate credentials into a \
session", "record a payment attempt and its outcome", "emit a \
subscription-changed event on transitions". Downstream \
comparch elaborates these into real pubapi signatures; at this \
tier we just need the action handles. Phrases like "handle \
X" or "manage Y" are category-speak — rewrite them as concrete \
verbs ("record", "resolve", "reconcile", "emit"). The cap at \
six keeps the sysarch-level API surface honest; if a component \
genuinely has more than six independent primary operations, \
split it.
* ``<responsibilities>`` contains one or more ``<resp \
id="resp_..."/>`` children. Each ``id`` must reference a \
top-level responsibility from the input list, verbatim. **Every \
top-level responsibility must be assigned to exactly one domain \
component.** A responsibility may additionally appear in one \
presentational component's ``<responsibilities>`` block, but \
only if that presentational component has a ``<domain-parent>`` \
edge to the domain component that owns the responsibility. This \
means a responsibility appears in either 1 component (domain \
only) or 2 components (domain + its presentational counterpart). \
Orphans and assignments to multiple domain components are \
structural errors.
* **Group responsibilities by shared data ownership and shared \
failure modes, not by shared category.** Two responsibilities \
that both touch the same entity but can fail independently of \
each other (one blocks a user-facing flow, the other silently \
degrades a background one) probably belong in different \
components even if the category label suggests otherwise. Two \
responsibilities that touch different entities but must succeed \
or fail together probably belong in the same component. When \
you have to choose, ask: which other responsibilities does this \
one *fail with*, and which does it *own data alongside*? Those \
are the real groupings. Category-clustering ("all the auth \
things go in Auth") produces components that have to be split \
later once the real coupling shows up.
* **Each external boundary deserves its own component.** \
Anything the system talks to over the wire — LLM provider \
APIs, git forges, identity providers (SSO/OIDC/SAML), \
notification channels (email, webhooks, team-messaging), \
payment processors, vector stores hosted as a separate \
service, telemetry sinks — is an *external boundary*. Each \
such boundary owns a distinct failure surface (provider \
outages, rate limits, credential rotation, schema drift, wire \
protocol versioning) that has nothing to do with the rest of \
the system's failure modes. Isolating each external \
integration into its own component means: (a) when the \
provider misbehaves, the blast radius is one component's \
sandbox/retry/circuit-breaker logic, not a smear across \
multiple components that each happen to call out; (b) credential \
handling, request signing, and quota tracking have one home \
per provider rather than being re-implemented per call site; \
(c) swapping providers (e.g. a different LLM, a different \
forge plugin) is a single-component substitution rather than \
a hunt across the codebase. Resist the temptation to fold an \
external-boundary's resps into the component that *uses* it \
("LLM dispatch lives in Generation Pipeline because that's \
where prompts are rendered") — the use site and the boundary \
have different failure modes and should be different \
components, with a dependency edge connecting them. The \
foundation component is the exception: cross-cutting platform \
infrastructure that genuinely every component reaches into \
stays foundation, not its own external-boundary component.
* **Resp-count is a strong split signal.** A single component \
that ends up with more than ~12 top-level responsibilities is \
almost always two components in disguise. The downstream \
comparch pass has to keep all of that surface internally \
consistent — invariants, primary-operations, public-surface, \
failure-surface, subcomp ownership — and the consistency \
budget runs out long before the resp count does. Concrete \
patterns that legitimately carry 12+ resps: (a) a foundation \
component owning shared substrate across many concerns; (b) \
a single coherent lifecycle hub where every resp is a \
transition or guard on the same aggregate (e.g. a draft \
state machine); (c) an event-log core where every resp is a \
projection or read-side query against the same append-only \
spine. Outside those patterns, when you find yourself listing \
13+ resps under one component, look for the seam: a clean \
read-vs-write split, a protocol-vs-content split, an \
external-boundary-vs-orchestration split, an \
authoring-vs-curation split. Splitting at sysarch time costs \
one extra component and a couple of dependency edges; \
*not* splitting forces comparch to manage 15-20 resps' worth \
of cross-section consistency under a single roof, which is \
the most common cause of mid-band comparch quality.

## Foundation component

* **Exactly one component must carry a self-closing \
``<foundation/>`` marker as a child.** This is the foundation \
component — it owns the project's root folder files (build \
config, package init, shared utilities, entry point) and \
anything that doesn't logically belong to another top-level \
component. See the architecture doc §Foundation components for \
why this is required.
* The foundation component is otherwise a normal component — \
it has its own name, purpose, owned-invariants, \
primary-operations, and at least one responsibility. The \
conventional default name is ``Foundation`` unless the project \
has a more specific convention.

## Policies

* Top-level policies live under ``<policies>``. Zero or more are \
permitted; if the project has no cross-cutting invariants that \
need explicit statement, emit ``<policies></policies>`` empty.
* **The reqs tier seeds policy-shaped atoms as ordinary resps** — \
names like "rate-limit outbound LLM calls per provider", "audit \
every credential access", "encrypt provider credentials at rest", \
"AGPL dependency hygiene" show up in the input resp list. For \
each one you make an architecture-informed judgment that the \
reqs pass could not: **is this actually cross-cutting, or is it \
local to one component's boundary?** Rate-limiting LLM calls is \
local if every LLM call flows through one gateway component — \
it's just a regular resp owned by that component, no policy \
needed. Rate-limiting is cross-cutting only if many components \
would independently call providers. "Reducer-only writes" is \
local (the rule lives at the reducer entrypoint). "AGPL \
dependency hygiene" is cross-cutting (every component adding a \
dep must honour it). **When in doubt, local wins — emit a \
regular resp assignment, not a policy.** Your ``<policies>`` \
block is authoritative; the reqs seeds are input signal. You \
decide.
* When a reqs-seeded atom is genuinely cross-cutting, emit a \
``<policy>`` naming its trigger with ``<required>`` pointing at \
the resp's ID — the resp still gets assigned to one domain \
component as its enforcer, and the policy adds application \
edges to every matching-trigger site. When a reqs-seeded atom \
is local, just assign it as an ordinary resp and omit the \
policy entirely — no double-encoding.
* Each ``<policy>`` contains exactly one ``<name>``, one \
``<trigger>``, one ``<rationale>``, and **zero or one** \
``<required>``. Most policies have a ``<required>``; universal-\
scope policies (see below) omit it.
* ``<trigger>`` is a short semantic phrase identifying where the \
policy applies: ``any LLM call``, ``any domain write``, \
``any authenticated request handler``. Semantic, not structural \
— different projects phrase triggers differently.
* ``<required>`` is a bare ``resp_*`` ID referencing the \
responsibility that must be fulfilled at every trigger site. \
The ID must be in the input top-level responsibility list. \
**Omit ``<required>`` entirely** for universal-scope policies \
— obligations that don't map to a single enforcing \
responsibility. Examples: an AGPL license obligation, an \
organization-wide naming convention, a cross-cutting security \
requirement that every component must honor without any one \
component owning "the security resp". The application pass \
treats these as "applies to every candidate component in \
scope" rather than patching a dep edge to a specific resp's \
owning component.
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
* **Every non-foundation component must have a `<dep>` edge \
pointing at the foundation component.** Foundation owns the \
project root — build config, shared utilities, base types, \
the application factory — and every other component's code \
reaches into it at runtime, so the dependency is mandatory and \
enforced by the validator. Foundation itself has no outbound \
dependencies and is the only sink in the dep DAG.
* Policies can induce additional dependency edges — if a policy \
says "any LLM call must fulfill ``resp_telemetry``," every \
component that has LLM-calling responsibilities needs a dep on \
whichever component fulfills ``resp_telemetry``. Reason about \
policies first, then emit ``<dependencies>`` so policy-induced \
deps land naturally on top of the mandatory foundation deps. \
This is why the section order puts ``<policies>`` before \
``<dependencies>``.
* **Acyclicity has architectural implications.** Because deps \
are acyclic, cross-cutting concerns (configuration, telemetry \
registration, route registration, middleware) cannot use mutual \
dependencies. A component that needs to know about all its \
dependents' shapes — a config loader that reads every \
component's config section, a telemetry registry that enumerates \
every component's events — must provide a **registration \
interface** that dependents call into, not import from \
dependents directly. The pattern is inversion of control: \
foundation (or whatever component owns the cross-cutting \
infrastructure) provides the machinery; each component \
registers its own contribution on startup. Design your \
components so that the flow of registration goes from \
dependents toward foundation, not the other way.

## Domain-parent

* Each ``<parent from="..." to="..."/>`` is a presentational → \
domain edge. The ``from`` alias must belong to a component with \
``<kind>presentational</kind>``; the ``to`` alias must belong \
to a domain component.
* **Each presentational has 1 or 2 ``<domain-parent>`` edges — \
3 or more is rejected by the validator.** Downstream comparch \
for the presentational pulls in domain pubapi fragments for \
fan-in context via these edges, and 3+ parents means the \
component is surfacing too much for one task. If the \
``<purpose>`` spans three or more domains, the solution is to \
split the presentational into multiple task-focused \
components, each with 1–2 parents — not to wire more edges on \
the original.
* A presentational component with no ``<domain-parent>`` edges \
is almost always a mistake — either it isn't actually \
presentational (and should be ``<kind>domain</kind>``), or its \
domain-parent edges are missing.

## Coverage

* Every top-level responsibility from the input list must be \
assigned to exactly one **domain** component's \
``<responsibilities>`` block. A responsibility may additionally \
appear in one presentational component if that presentational \
component is the domain parent's counterpart (has a \
``<domain-parent>`` edge to it). Missing assignments and \
assignments to multiple domain components are structural errors.

## Meta-rules

* Do not include commentary about what you are doing or how you \
arrived at the list. Output only the ``<sysarch>`` block.
* Unescaped ``&`` and ``<`` inside ``<purpose>`` / ``<invariant>`` \
/ ``<operation>`` / ``<runtime>`` / ``<persistence>`` / \
``<write-path>`` / ``<concurrency>`` / ``<testing>`` / \
``<deploy>`` / ``<technologies>`` / ``<rationale>`` text are \
fine — the parser tolerates them.
"""


def render_system_prompt() -> str:
    """Return the sysarch system prompt."""
    from backend.graph.prompts._change_summary import change_summary_instruction

    return _SYSTEM_PROMPT_TEMPLATE + change_summary_instruction()


def render_user_prompt(
    *,
    features_summary: str,
    reqs_summary: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    prior_review: str | None = None,
    parse_error: str | None = None,
    vocab_summary: str = "",
    input_doc: str = "",
    referenced_content_summary: str = "",
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

    ``input_doc`` is the raw project input document. The handler
    passes it on every generation so the LLM sees the original
    framing for both initial drafts and feedback iterations. See
    the matching comment in
    :mod:`backend.graph.prompts.requirements`.
    """
    parts: list[str] = []
    if input_doc and input_doc.strip():
        parts.append("# Project input document")
        parts.append("")
        parts.append(input_doc.strip())
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
    parts.append("# Project features (approved upstream)")
    parts.append("")
    parts.append(features_summary.strip() or "(no features minted yet)")
    parts.append("")
    parts.append("# Top-level responsibilities (approved upstream)")
    parts.append("")
    parts.append(reqs_summary.strip() or "(no responsibilities minted yet)")
    parts.append("")

    # Split the prior round's <introduction> out from the body so
    # the model sees its prior thinking as historical commentary
    # rather than live framing for the new round. Without this, the
    # introduction's references to prior feedback bleed forward and
    # each regen anchors on stale critique.
    prior = prior_pending or prior_approved
    prior_intro, prior_body = split_prior_introduction(prior)
    parts.extend(render_prior_framing_section(prior_intro))
    if prior_body:
        parts.append("# Current version")
        parts.append("")
        parts.append(prior_body)
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
    elif feedback and prior:
        parts.append(
            "Revise the system architecture to address the user "
            "feedback above. Preserve the component + policy + edge "
            "set where the feedback does not require a change. Output "
            "only the revised <sysarch> block."
        )
    elif prior:
        parts.append(
            "Improve the system architecture above. Fix any issues you "
            "notice with component boundaries, handle quality, "
            "responsibility assignments, or dependency structure. "
            "Output only the revised <sysarch> block."
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
