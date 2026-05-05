"""Prompt template for the component-architecture (``comparch``) draft.

The comparch pass is the Phase 4 per-component deep dive. Each
top-level ``comp_*`` gets an architecture doc that describes its
role-level techspec, public/private API surfaces, component-local
policies, external dependencies to sibling top-level components,
and its own subcomponent decomposition. **Comparch is also where
the parent responsibilities assigned to this component get carved
into subcomp-shaped slices** — there is no longer an intermediate
subreqs tier; the LLM declares per-subcomp ownership of (parent
resp, feat-slice) pairs directly via the ``<owns>`` block.

Default is **single-owner**: each parent resp gets one
subcomponent that anchors it. Multi-owner is legal but
*exceptional* — the validator allows it, but the generator
prompt reserves it for two named patterns (UI flow splits and
read/write path splits) where the work genuinely cooperates
across subcomp seams. See ``## The <owns> block`` for the
detailed rule.

Output format (parsed by :mod:`backend.graph.parsers.xml_sections`
and validated by
:func:`backend.graph.parsers.validators.validate_arch_doc`):

    <comparch>
      <technical-specification>…role-level techspec…</technical-specification>
      <public-surface>…types / signatures / events…</public-surface>
      <private-surface>…internal types + helpers…</private-surface>
      <failure-surface>…concrete failure modes this component produces…</failure-surface>
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
          <purpose>…one sentence…</purpose>
          <owned-invariants>
            <invariant>…</invariant>
            <invariant>…</invariant>
          </owned-invariants>
          <primary-operations>
            <operation>…</operation>
            <operation>…</operation>
            <operation>…</operation>
          </primary-operations>
          <responsibilities>Free text — what this subcomp does.</responsibilities>
          <owns>
            <resp id="resp_payment01">
              <feat id="feat_payment_v01"/>
            </resp>
          </owns>
          <foundation/>
        </subcomponent>
      </subcomponents>
      <sub-dependencies>
        <dep from="cache" to="foundation_sub"/>
      </sub-dependencies>
    </comparch>

Eight sections in fixed order. First four are fragments
(persistent, transcluded into dependents' regen prompts). Last
two are mint-time directives: ``<subcomponents>`` mints
``comp_*`` children plus ``decomposition`` edges from each claimed
parent resp / feat to the owning subcomp, and
``<sub-dependencies>`` emits dependency edges between subcomps.
Both may be empty for un-fanned-out components that will grow a
single ``impl_*`` leaf instead.

Design notes:

- ``<dependencies>`` uses **real** ``comp_*`` IDs (sibling top-level
  components are globally unique and already minted by sysarch).
- ``<sub-dependencies>`` uses **local aliases** (subcomponents are
  minted by the mint handler at approval time, so their IDs don't
  exist yet at generation time).
- Subcomponents inherit their kind (domain / presentational) from
  the owning component and do not redeclare it.
- Policies come before dependencies for the same reason as sysarch:
  a policy can induce a dep edge, so the LLM reasons about policies
  first and the resulting deps land naturally in the next section.
- ``<responsibilities>`` is now **free-text prose** describing what
  the subcomp does; the structured "which parent resp does this
  subcomp claim a slice of" data lives in ``<owns>`` for
  validator-checked coverage.

See ``docs/architecture/v2-rearchitecture.md`` §Architecture
documents are parseable, §Policies, §Foundation components, and
``docs/architecture/v2-roadmap.md`` Phase 4.
"""

from __future__ import annotations

from backend.graph.prompts._prior_framing import render_prior_review_section

_SYSTEM_PROMPT_TEMPLATE = """\
You are producing the **architecture document** for a single \
component. This is the **last compression step** before \
implementation. Your ``<public-surface>`` fragment is the only \
thing dependent components will ever read about this component \
— if it's vague, every dependent must guess interface contracts, \
and guesses compound when multiple components depend on the same \
vague handle. Your ``<technical-specification>`` is what \
subcomponent arch docs (Phase 5) will inherit and narrow, and \
what implementation nodes will read to choose libraries and \
patterns. Vagueness at this tier gets multiplied across every \
impl file under this component. The pressure on handle quality \
is highest here.

**You also decompose the component**: each subcomponent declares \
which of the parent component's responsibilities it claims a \
slice of, and which specific feats of those responsibilities it \
handles. Aim for **single-owner**: each parent resp anchored by \
exactly one subcomponent. Multi-owner is allowed but reserved \
for two named patterns where the cooperation is real, not \
incidental — see ``## The <owns> block`` below.

You will be given the component's metadata from the \
system-architecture pass (name, role paragraph, intended API), \
the top-level responsibilities assigned to it (each with its \
feat-tag set), the list of sibling components it may declare \
dependencies on, the public surfaces of any of those siblings \
that are already fully architected, the top-level policy \
candidates the system has minted so far, and optionally prior \
approved / pending drafts, user feedback, and parse-validate \
errors.

Your job is to produce a single ``<comparch>`` block containing \
eight sections in a fixed order: a role-level technical \
specification, the component's public surface, its private \
surface, the concrete failure surface this component can \
produce, the policies it mints locally, its external \
dependencies, its subcomponent decomposition (with per-subcomp \
``<owns>`` claims on parent resps + feat slices), and the \
dependency edges between subcomponents. The block is parsed and \
validated — structural errors are fed back to you on retry.

# Output format

Emit exactly one ``<comparch>`` block with these eight children \
in this order: ``<technical-specification>`` → \
``<public-surface>`` → ``<private-surface>`` → \
``<failure-surface>`` → ``<policies>`` → ``<dependencies>`` → \
``<subcomponents>`` → ``<sub-dependencies>``. \
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
      <failure-surface>
    Credential-verifier regression admits empty-hash matches and \
    lets any attacker sign in as any account (auth bypass); a bug \
    in session rotation issues duplicate active sessions for one \
    principal (silent identity-state divergence); session-store \
    writes bypassing the reducer corrupt the audit trail (log \
    drift, platform-integrity incident).
      </failure-surface>
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
          <purpose>Owns session rows and answers token lookups.</purpose>
          <owned-invariants>
            <invariant>every row has a single active principal</invariant>
            <invariant>expired tokens are rotated on read</invariant>
          </owned-invariants>
          <primary-operations>
            <operation>create a session for a principal</operation>
            <operation>resolve a token into a session</operation>
            <operation>rotate expired sessions</operation>
          </primary-operations>
          <responsibilities>Persists session state and serves token lookups for the
    component's other subcomps and outside dependents.</responsibilities>
          <owns>
            <resp id="resp_session01">
              <feat id="feat_authsess01"/>
              <feat id="feat_authrefr02"/>
            </resp>
          </owns>
        </subcomponent>
        <subcomponent alias="credential_gate">
          <name>CredentialGate</name>
          <purpose>The single site that verifies plaintext credentials.</purpose>
          <owned-invariants>
            <invariant>raw credentials never leave this subcomponent</invariant>
            <invariant>hash comparison uses constant-time equality</invariant>
          </owned-invariants>
          <primary-operations>
            <operation>verify credentials and return a principal id</operation>
            <operation>delegate session creation to the session store</operation>
            <operation>emit a failed-auth event on mismatch</operation>
          </primary-operations>
          <responsibilities>Verifies plaintext credentials, hands off to SessionStore to mint
    a session on success, emits failed-auth events on mismatch.</responsibilities>
          <owns>
            <resp id="resp_authn0001">
              <feat id="feat_login0001"/>
            </resp>
            <resp id="resp_session01">
              <feat id="feat_authsess01"/>
            </resp>
          </owns>
        </subcomponent>
        <subcomponent alias="foundation">
          <name>AuthCore</name>
          <purpose>Owns this component's root folder and shared base types.</purpose>
          <owned-invariants>
            <invariant>shared base types stay versioned together</invariant>
            <invariant>one source of truth for component settings</invariant>
          </owned-invariants>
          <primary-operations>
            <operation>load settings from the environment</operation>
            <operation>configure logging for this component</operation>
            <operation>expose shared base classes</operation>
          </primary-operations>
          <responsibilities>Component-internal plumbing — settings loader, logging config,
    shared base classes. No parent resp claims.</responsibilities>
          <owns/>
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

Cross-section consistency is the property that distinguishes a \
usable comparch from one impl will fight. The most common defect \
this tier produces is two sections that disagree — an \
``<invariant>`` claiming "X never happens" alongside a \
``<failure-surface>`` entry describing X happening, a techspec \
promising atomicity alongside a failure mode that requires \
non-atomicity, a public-surface return type that cannot express \
a failure the failure surface explicitly names, a primary-\
operation that no public or private surface entry mounts. Treat \
the eight sections as a single document throughout generation, \
not as eight independent sections you reconcile at the end. The \
rules below are written so that following each section's rules \
produces sections that already agree; the self-checks at the \
end are a final scan, not the place where consistency gets \
introduced.

**Names create semantic obligations.** Every named identifier \
this comparch emits — subcomp name, type name, sum-type variant, \
field name, parameter name — advertises a contract the rest of \
the document must honour. A sum type called \
``blocking_reason :: :ready | :running | :throttled`` is a \
contradiction; if ``:ready`` and ``:running`` aren't blocking \
scenarios the type is mis-named, and either rename it \
(``node_state``) or drop the non-blocking variants. A parameter \
called ``highlight`` claims the public surface threads it \
through to a rendering consumer; if the techspec and private \
surface never resolve it to anything, the parameter is a dead \
promise, and either wire it up or strike it. A subcomponent \
called ``X Dispatcher`` claims X is what it dispatches; if it \
orchestrates Y and dispatches Z, rename to match. Before \
emitting any named identifier, read it back as a contract: what \
does this name promise? Then verify the rest of the doc honours \
that promise. Names that overstate are the second-most-common \
contradiction shape after invariant overreach.

## Structure

* Emit **exactly one** ``<comparch>`` root block. Nothing before, \
nothing after.
* The eight children **must appear in this order**: \
``<technical-specification>`` → ``<public-surface>`` → \
``<private-surface>`` → ``<failure-surface>`` → ``<policies>`` → \
``<dependencies>`` → ``<subcomponents>`` → ``<sub-dependencies>``. \
Out-of-order sections are a structural error.
* No unknown top-level children under ``<comparch>``.

## Fragment sections (techspec / pubapi / privapi / failure-surface)

* ``<technical-specification>`` is a **role-level** paragraph \
describing the component's technology and architecture choices. \
Subcomponent arch docs (Phase 5) will inherit and narrow this \
techspec. Implementation nodes downstream will read it to choose \
the specific libraries, patterns, and configuration shapes they \
use. Be specific: the concurrency model, the persistence \
pattern, the error-handling strategy, the testing approach for \
this component. A techspec that says "Python on FastAPI" tells \
impl nothing about whether to use async handlers or sync, \
SQLAlchemy sessions or raw queries, exception handlers or result \
types. **No** per-subcomponent sequencing, no implementation \
walkthroughs. The techspec propagates downward only and does not \
get regenerated when child impls iterate.
* Structure the spec as paragraphs separated by a blank line \
(``\n\n``). Each paragraph addresses one concern — concurrency, \
persistence, error handling, testing. Don't use bullet lists or \
headings; the downstream renderer splits on blank lines and \
wraps each paragraph in its own block.
* ``<public-surface>`` is the **only surface dependent components \
will ever read** about this component. Types, function \
signatures, method signatures, events. Code-shaped content lives \
in fenced code blocks; any language is fine. Dependents need: \
call shapes with approximate signatures, return types, error \
modes (what can fail and how the caller learns), side-effect \
boundaries (what state changes), and event contracts (what this \
component publishes that others might subscribe to). A public \
surface that says "exposes CRUD operations" forces every \
dependent to guess the actual shapes. Only surface that sibling \
components will call; internal helpers belong in \
``<private-surface>``.
* ``<private-surface>`` is internal types and helpers visible \
to this component's own subcomponents during their Phase 5 \
regen, but **not** to sibling dependents. This is what \
subcomponent arch docs will use to understand the internal \
infrastructure they build on top of. Same fenced-code-block \
convention as the public surface.
* ``<failure-surface>`` names the **residual risks that survive \
the component's invariants** — coverage gaps in checks the \
invariants describe, race windows that bound otherwise-strong \
guarantees, observable consequences of best-effort or eventually-\
consistent behavior, and concrete wrong-output shapes the type \
system cannot prevent. **Failure-surface entries are not \
violations of invariants.** If you find yourself writing one \
that contradicts an invariant or a techspec promise, fix one of \
them first — either the invariant is overclaiming and needs \
weakening, or the failure mode is fabricated. The two sections \
must agree.
* Each entry names three things: (a) the **mechanism** that \
fails — what specific code path or interaction leaks the failure, \
not "the system fails"; (b) the **observable shape** — what \
return value, event, or state the caller sees that differs from \
intended, in the same terms as the public surface; (c) the \
**detection characteristic** — silent until runtime, surfaces \
immediately as a typed error, eventually consistent within \
window W, etc. Pack multiple distinct failure modes into one \
paragraph separated by semicolons. Good shape: "YAML parser \
silently coerces ambiguous values like bare on/off tokens, \
producing {:ok, schema} with corrupted fields invisible until \
downstream runtime behavior diverges." Bad: "service becomes \
unreliable", "data issues", "users affected".
* **When the techspec commits to a typed error discipline** \
(Elixir tagged tuples, Rust ``Result``, TypeScript discriminated \
unions, Go's typed errors), every entry in the failure surface \
must have a corresponding variant in the public-surface return \
type. The pubapi's error union becomes the consistency anchor: \
failure modes the type cannot express are silent failures, not \
residual risks. If you cannot find a matching variant, either \
add one to pubapi or strike the failure mode from the surface.
* All four fragment sections must be non-empty. Do not put \
nested XML tags inside them — only prose and fenced code blocks.

## Policies

* ``<policies>`` is zero or more component-local ``<policy>`` \
entries. Each policy has exactly one ``<name>``, one \
``<trigger>``, one ``<rationale>``, and **zero or one** \
``<required>``.
* ``<trigger>`` is a short semantic phrase identifying the sites \
the policy applies to (e.g. "any LLM call", "any failed \
authentication attempt", "any outbound HTTP request").
* ``<required>`` is a single ``resp_*`` ID. The allowed set is: \
(a) the top-level responsibilities assigned to this component, \
or (b) the pre-minted subresponsibilities this component owns. \
Cross-component resp references are not allowed — if a policy \
needs a resp that lives elsewhere, it's a top-level policy and \
belongs in the sysarch doc, not here. **Omit ``<required>`` \
entirely** for universal-scope policies that every subcomponent \
in this component's subtree should honor without any single \
sub owning enforcement (e.g. a cross-cutting invariant that all \
sub-comp code must satisfy). The application pass then attaches \
the policy to every subcomp candidate in scope.
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
``<purpose>``, one ``<owned-invariants>``, one \
``<primary-operations>``, one ``<responsibilities>``, and one \
``<owns>`` block. Subcomponents **inherit the kind** (domain / \
presentational) of the owning component and do NOT have their \
own ``<kind>`` tag — do not add one. The micro-field grammar \
matches the sysarch Component grammar deliberately; downstream \
readers get one schema at both tiers.
* ``<name>`` is a short identifier — title case. **Match name \
specificity to responsibility specificity.** A subcomp with \
domain-specific invariants and operations gets a domain-specific \
name ("SessionStore", "CredentialGate", "PaymentReconciler"). A \
subcomp that is genuinely generic infrastructure — a registry \
of provider adapters, a gateway over external SaaS calls, a \
dispatcher routing to per-tier handlers — gets a structural \
name ("ProviderAdapterRegistry", "WebhookGateway", \
"DispatcherCore"). The anti-pattern is wrapping domain logic \
in a generic shell ("BillingManager" for payment-reconciliation \
logic, "AuthService" for credential-verification logic) — that \
hides what the subcomp actually owns. If your subcomp's \
invariants and operations name a specific domain concern, the \
name must too; if they name a generic plumbing concern, the \
name should reflect that plumbing role rather than dressing it \
up.
* ``<purpose>`` is the one-sentence reason this subcomponent \
exists. The subcomparch pass (Phase 5) reads it first when \
deciding the subcomponent's internal structure, and impl nodes \
read it to frame what code they're writing. Name the \
subcomponent-distinctive *why*, not the category. "The single \
site that verifies plaintext credentials" is a handle; "handles \
credentials" is category-speak. If you need an ``and``, consider \
whether the subcomponent is actually two.
* ``<owned-invariants>`` lists **2-4 short noun phrases** naming \
the durable state or guarantees this subcomponent owns. \
Concrete enough that a reviewer can point at the impl and say \
yes/no. If you find yourself listing more than four, push the \
extras to implementation detail; if fewer than two, the \
subcomponent's role is too thin.
* **Phrase invariants as structural facts, not procedural \
promises.** This is the single highest-leverage rule for this \
section. Procedural phrasing ("every X does Y", "X always \
succeeds", "no X ever happens") invites the failure surface to \
contradict the invariant. Structural phrasing ("X is the only \
path to Y", "Y is a deterministic function of X", "Z's content \
commits before W is dispatched", "the schema declares exactly \
title and body fields") lets the failure surface describe \
coverage gaps and residual risks without contradiction. The \
clearest tell: a structural invariant survives the question \
"what if a future code path skips this check?" — that scenario \
becomes a coverage gap in the structural commitment, not a \
contradiction. A procedural invariant collapses on the same \
question.

  Worked example. *Procedural*: "every tool invocation checks \
the instigation guard before dispatching." The failure surface \
inevitably writes "a code path dispatches without calling the \
guard" — direct contradiction. *Structural rewrite*: "the \
instigation-guard module is the sole call path tool handlers \
traverse to reach mutation dispatch." Now the same failure-\
surface entry reads as a coverage gap in the call-graph design \
— consistent with the invariant.

  More examples of the rephrase:

  - "every credential decryption emits an audit event" → "the \
audit-emit primitive is on the only path through which \
decryption returns to the caller; calls that bypass it are \
rejected by the type system".
  - "approving the same bootstrap content twice produces the \
same event sequence" → "mint is a pure deterministic function \
of approved content".
  - "every LLM call records token telemetry" → "the gateway is \
the sole entry to provider APIs and runs telemetry recording \
inline before returning".

  Good concrete invariants regardless of phrasing style: "raw \
credentials never leave this subcomponent" (structural — the \
boundary is a fact about the call graph), "hash comparison uses \
constant-time equality" (structural — a property of the \
implementation choice), "every row has a single active \
principal" (structural — a uniqueness property of the data).
* ``<primary-operations>`` lists **3-6 short verb phrases** \
naming the operations callers (sibling subcomponents or outside \
dependents) invoke on this subcomponent. Examples: "verify \
credentials and return a principal id", "rotate expired \
sessions". Phase 5 elaborates these into real pubapi signatures; \
at this tier we just need the action handles. No "handle X" / \
"manage Y" category verbs — rewrite as concrete actions.
* ``<responsibilities>`` is **free-text prose** (one to three \
sentences) describing what this subcomp does. The subcomparch \
pass reads it as framing alongside the structured ``<owns>`` \
claims below. Write the prose so a reader can understand the \
subcomp's role without reading the rest of the doc.

## The `<owns>` block (parent-resp + feat-slice claims)

This is where the structured decomposition lives. Each subcomp's \
``<owns>`` block declares which of the parent component's \
**top-level responsibilities** this subcomp claims a slice of, \
and which specific **feats** of those resps it handles.

Shape:

    <owns>
      <resp id="resp_payment01">
        <feat id="feat_payment_v01"/>
        <feat id="feat_3ds_chal01"/>
      </resp>
      <resp id="resp_invoice02">
        <feat id="feat_invoice_v01"/>
      </resp>
    </owns>

* Every ``<resp id=...>`` must match one of this component's \
**parent responsibilities** shown in the input list (the resps \
sysarch assigned to this comp via decomposition edges). No \
cross-component leaks; no invention; no renaming.
* Every ``<feat id=...>`` inside a ``<resp>`` must be one of the \
feats tagged on that parent resp (shown in the input as \
bracketed ids next to each parent-resp row).
* **Default is single-owner**: each parent resp gets one \
subcomp that anchors it. Multi-owner is legal but reserved for \
two specific patterns where the work genuinely splits along a \
seam. **Outside these patterns, do not double-claim a resp** — \
if you find yourself reaching for it, the decomposition axis is \
probably wrong; refactor the subcomp boundaries instead.
* **Recognized multi-owner pattern 1: UI flow split.** A \
presentational component decomposing along interaction stages \
(per-element form / validation / submission / error display) \
will frequently have all stages claiming the same parent resp \
because each stage handles a slice of the same user-visible \
flow. The seam is "what stage of the interaction is this?", not \
"what data does this touch?". When you use this pattern, every \
subcomp claiming the shared resp must name its stage in the \
free-text ``<responsibilities>`` (e.g., "owns the validation \
stage of feat_payment01; co-owners: card_input handles capture, \
submit_flow handles server submission").
* **Recognized multi-owner pattern 2: read-path / write-path \
split.** A domain component decomposing into a query-side \
subcomp (read path) and a mutation-side subcomp (write path) \
that legitimately co-own the same parent resp because the same \
feat manifests on both sides of the data direction. The seam \
is "which direction does the data flow?". When you use this \
pattern, the read-side subcomp's ``<responsibilities>`` should \
say "read path for resp_X; co-owns with X_writer" and the \
write-side subcomp's prose should say the symmetric thing.
* **No other multi-owner patterns are accepted by the prompt.** \
If your decomposition needs three subs claiming the same resp, \
or two subs claiming the same resp without one of the two \
seams above, the validator may accept it but the reviewer will \
flag it and impl will be confused about who's accountable. \
Refactor instead.
* **Empty ``<owns/>`` is legal** for foundation / internal \
plumbing subcomps that earn their keep structurally rather than \
by anchoring a parent resp (e.g., a settings loader, shared \
base types, a lock manager). Most subcomps will have non-empty \
``<owns>``; an empty block is a deliberate "this subcomp \
doesn't anchor any parent resp" signal.
* **Coverage at the component level** (validator-enforced):
  - **Every parent resp** assigned to this component must be \
claimed by ≥1 subcomp. A parent resp with no claimants is a \
coverage gap.
  - **Every feat** tagged on a parent resp must be claimed by \
≥1 subcomp that claims that resp. A feat with no owning subcomp \
under its parent resp is a coverage gap.
* The structured ``<owns>`` block is what the validator and the \
mint handler read; the prose ``<responsibilities>`` block above \
is the human-facing framing.

## Per-medium decomposition guidance

How you draw subcomp boundaries depends on the component's \
**medium** (its kind + purpose):

* **Presentational components (kind=presentational)** front a \
domain via UI, CLI, dashboard, docs site, etc. Subcomp \
boundaries naturally split along **interaction surfaces**: per \
form, per view, per flow stage (input collection, validation, \
submission, error display, navigation). A "Card Payment Form" \
component might decompose into ``card_input`` (form rendering), \
``input_validation`` (sync field-level validation), \
``submit_flow`` (server submission + retry), \
``error_display`` (inline + summary error UX). When the \
interaction stages all act on the same user-visible feat, \
that's the **UI flow split** multi-owner pattern — each stage \
co-claims the shared resp and its prose names its stage. \
Outside that pattern, prefer single-owner (one resp anchored \
by the stage that genuinely owns it).
* **Domain components (kind=domain)** own data and operations. \
Subcomp boundaries naturally split along **data/operation \
seams**: per persistence layer (writer / reader / cache), per \
operation kind (sync API / async worker), per concern (lock \
manager / idempotency tracker / event emitter). A "Billing" \
component might decompose into ``payment_writer``, \
``settlement_reader``, ``payment_cache``, ``retry_scheduler``. \
Multi-owner is rare on domain components: the legitimate \
case is **read-path / write-path split** — query subcomp + \
mutation subcomp co-owning a resp because the same feat \
manifests on both sides of the data direction. A cross-cutting \
sub like ``retry_scheduler`` should anchor its own resps \
(retry-policy, dead-letter routing) rather than re-claim feats \
from payment-collection and invoice-delivery resps.

If your decomposition's subcomp names sound like the parent \
component's name with a noun suffix ("BillingService" → \
``billing_writer``, ``billing_reader``, ``billing_cache``), \
that's usually fine for domain components. If they sound like \
flow stages or UI elements, that's usually right for \
presentational components. **Mismatches are a smell**: a \
domain component decomposing along UI-interaction lines \
suggests the work actually belongs in a presentational \
component upstream.

## Un-fanned-out components

A component may legitimately choose **not** to decompose into \
subcomponents — especially small components that already fit in \
a single code territory. In that case:

* Emit ``<subcomponents></subcomponents>`` empty.
* Emit ``<sub-dependencies></sub-dependencies>`` empty.
* No foundation subcomponent is required.
* The component's parent responsibilities will be projected \
wholesale into a single ``impl_*`` leaf attached directly to \
this component instead. Coverage rules degenerate to no-ops in \
this case.

Un-fanned-out is the right choice when a component's \
responsibilities are all tightly coupled to the same code \
territory and splitting them would create artificial seams. \
Decomposing is the right choice when the responsibilities \
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
subcomponent with its own name, purpose, owned-invariants, \
primary-operations, and at least one responsibility. **Do \
NOT name it ``Foundation``.** That bare name is reserved for \
the project's top-level Foundation component, and reusing it \
as a subcomp name collides with the sibling-component roster \
every time this comparch's parent has Foundation as a \
sibling. The alias attribute (``alias="foundation"``) stays \
fine because aliases are local; the visible ``<name>`` must \
be component-specific. Use a name that reflects this \
subcomp's role inside the component — its substrate \
contribution (``AuthCore``, ``BillingPlumbing``, \
``GraphSubstrate``), shared-types responsibility \
(``BillingSharedTypes``, ``RuntimeShell``), or runtime concern \
(``BillingRuntime``, ``AuthRuntimeBootstrap``). The name \
should still read as the component-internal catch-all; it \
just must not be the bare token "Foundation".

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


## Final-scan checklist before emitting

The framing at the top of these rules and the section-specific \
rules above are written so that following them produces an \
artifact whose sections agree. Before you write the closing \
``</comparch>`` tag, run this short final pass to catch any \
remaining gaps. If a scan finds a contradiction, fix the \
artifact — do not rationalize it.

Parser-enforced violations don't need manual verification (the \
parser will reject and feed back on retry): declared sub-\
dependency cycles, private modules referenced by full module \
name in ``<public-surface>``, missing parent-resp coverage \
when ``<subcomponents>`` is non-empty, per-resp feat-coverage \
gaps, foundation subcomponent missing or duplicated.

The scans below are not parser-enforced — they are where the \
most-cited defects in this tier live:

* **Cross-section consistency (highest-yield).** Re-read \
``<failure-surface>`` against every ``<invariant>`` and every \
techspec promise (atomicity, ordering, single-frame render, \
no-truncation, single-event semantics). A failure mode that \
contradicts an invariant or a techspec promise means one of \
them is wrong — usually the invariant is procedurally phrased \
("every X does Y") and needs the structural rephrase from the \
invariant rules above; sometimes the failure mode is \
fabricated. Same scan against public-surface return types: \
every failure mode must have a matching variant in the typed \
pubapi (when the techspec commits to a typed error \
discipline). A failure mode the public API cannot express is \
silent — fix by adding the variant or striking the entry.

* **Surface closure — both directions.**

  *Pass A — every public-surface element has an owner.* For \
every type, struct, event, function, and field in \
``<public-surface>``, identify the subcomp's primary-operation \
that produces or invokes it. Pubapi entries with no producer \
are dead or missing operation coverage. Every type named in a \
public-surface signature must be defined in public-surface \
itself, be a language primitive / stdlib type, or come from a \
declared external dependency. **Nothing in a public-surface \
signature may reference a type or struct from \
``<private-surface>``** — siblings would have to reach into \
your internals. Promote private types to public if load-\
bearing, otherwise rewrite the public reference using only \
already-public types. The parser catches the obvious version \
(private module names in public specs); your scan covers the \
indirect version (a public type whose field references a \
private struct).

  *Pass B — every internal commitment surfaces somewhere.* \
For every invariant or primary-operation that names a side \
effect, response, event, or value (published, returned, \
persisted, dispatched), identify the public-surface or \
private-surface entry that mounts it. An operation claimed \
but not mounted on a surface is half-done. Symmetrically, \
every private-surface entry must back at least one primary-\
operation; private helpers with no operation reference \
shouldn't have a private-surface entry at all.

* **Dependency grounding — external AND internal.**

  *External:* For each ``<dep to="comp_..."/>``, confirm the \
techspec or a primary-operation describes how this component \
actually uses the sibling — what data flows, which sibling \
pubapi gets called, what event gets subscribed to. Ungrounded \
external deps are spurious (delete) or evidence of unwritten \
prose (write).

  *Internal:* For each ``<sub-dependencies>`` edge, confirm \
the source subcomp's primary-operations or responsibilities \
text describes calling into the target subcomp. \
**Symmetrically**, walk every subcomp's operations / \
invariants / responsibilities / purpose for cross-subcomp \
call sites implied by the prose; each one needs a declared \
``<dep from="A" to="B"/>`` edge. Implicit cross-sub \
references without declared edges are rejected at parse time \
when they form a cycle (the validator unions implicit edges \
from subcomp-name mentions with declared edges before cycle \
detection); even cycle-free cases leave the coupling graph \
incomplete. Either declare the edge or rephrase the prose to \
remove the call reference.

* **Single-owner default.** Re-read all ``<owns>`` blocks. \
Any parent resp claimed by more than one subcomp must fit the \
UI flow split or read/write path split pattern; otherwise \
refactor the subcomp boundaries.

* **Rationale, not inventory.** For each subcomp's \
``<purpose>``, each ``<invariant>``, each \
``<primary-operation>``, and the ``<responsibilities>`` prose, \
ask whether it names a distinctive *why* or a list of \
contents. Rewrite category-speak ("handles X", "manages Y", \
"aggregates Z", "contains W") into concrete actions and \
distinctive rationale. The foundation subcomp's purpose names \
the substrate role it plays, not its contents.

## Meta-rules

* Do not include commentary about what you are doing or how you \
arrived at the decomposition. Output only the ``<comparch>`` \
block.
* Unescaped ``&`` and ``<`` inside fragment-section text (outside \
the XML tags themselves) are tolerated by the parser.
"""


def render_system_prompt() -> str:
    """Return the comparch system prompt."""
    from backend.graph.prompts._change_summary import change_summary_instruction

    return _SYSTEM_PROMPT_TEMPLATE + change_summary_instruction()


def format_domain_parent_surface(
    parents: tuple,
    techspecs: dict[str, str],
    pubapis: dict[str, str],
    fanins: dict[str, str] | None = None,
) -> str:
    """Render the Phase 6 "what you're presenting" context block.

    ``parents`` is a tuple of domain ``comp_*`` Node rows reached
    by the ``domain_parent`` edges this (presentational) comparch
    target points at. ``techspecs`` and ``pubapis`` map each
    parent's ``comp_*`` id to the content of its corresponding
    fragment; missing or empty fragments collapse to omitted
    sections. When ``parents`` is empty the helper returns ``""``
    and the prompt omits the whole block — which is what happens
    for every domain component and for presentational components
    whose ``domain_parent`` edges haven't been drawn yet.

    Phase 7: ``fanins`` optionally maps each parent's ``comp_*``
    id to the serialized ``<fanin>`` block synthesized from that
    parent's subtree of impls. When present, the per-parent
    subsection renders the fan-in below the techspec + pubapi
    under a "*As built (fan-in synthesis):*" header. The LLM
    sees the top-down design intent (techspec / pubapi) and the
    bottom-up built reality (fan-in) side-by-side and can
    surface drift in its own output. Missing or empty fan-in
    entries collapse to the pre-Phase-7 view — un-fanned-out
    domain parents and parents whose impls haven't been
    approved yet both fall through cleanly.

    The output is markdown with one ``## <name> (`comp_id`)``
    subsection per parent, each carrying at most three fenced
    blocks (techspec, pubapi, fan-in). The fencing keeps the
    rendered fragments from being mistaken for prompt
    directives by the LLM; the calling ``render_user_prompt``
    wraps the whole thing in a ``# This component presents``
    section header with framing prose that tells the LLM how
    to use the material.
    """
    if not parents:
        return ""
    fanins = fanins or {}
    lines: list[str] = []
    for parent in parents:
        name = getattr(parent, "name", "") or "(unnamed)"
        pid = getattr(parent, "id", "")
        lines.append(f"## {name} (`{pid}`)")
        techspec = (techspecs.get(pid, "") or "").strip()
        pubapi = (pubapis.get(pid, "") or "").strip()
        fanin = (fanins.get(pid, "") or "").strip()
        if techspec:
            lines.append("")
            lines.append("*Technical specification (domain side, top-down intent):*")
            lines.append("")
            lines.append("```")
            lines.append(techspec)
            lines.append("```")
        if pubapi:
            lines.append("")
            lines.append("*Public surface (domain side, top-down intent):*")
            lines.append("")
            lines.append("```")
            lines.append(pubapi)
            lines.append("```")
        if fanin:
            lines.append("")
            lines.append("*As built (bottom-up fan-in synthesis):*")
            lines.append("")
            lines.append("```")
            lines.append(fanin)
            lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_user_prompt(
    *,
    component_summary: str,
    parent_resps_summary: str,
    sibling_comps_summary: str,
    dep_pubapi_summary: str,
    top_level_policy_candidates_summary: str,
    related_features_summary: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    prior_review: str | None = None,
    parse_error: str | None = None,
    target_is_foundation: bool = False,
    vocab_summary: str = "",
    domain_parent_surface: str = "",
    referenced_content_summary: str = "",
) -> str:
    """Build the user prompt for the comparch generator.

    All context sections are passed in as pre-formatted strings.
    The stage 2 ``regen_context`` helper produces them from the
    component's DB state; for unit tests they can be supplied
    directly.

    - ``component_summary``: component name + role + api-intent
      (the sysarch-time fragment content as context).
    - ``parent_resps_summary``: top-level resps assigned to this
      component, each rendered with its name + bracketed feat-id
      list. The LLM echoes resp ids into ``<owns><resp id=…>``
      and feat ids into ``<owns><resp><feat id=…>``.
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
    parts.append(
        "Each parent resp is rendered with its name and bracketed "
        "feat-id list. The LLM echoes resp ids into "
        "``<owns><resp id=…>`` and feat ids into the nested "
        "``<feat id=…>`` children."
    )
    parts.append("")
    parts.append(parent_resps_summary.strip() or "(no responsibilities assigned)")
    parts.append("")
    parts.append("# Sibling components (allowed <dependencies> targets)")
    parts.append("")
    parts.append(sibling_comps_summary.strip() or "(no siblings)")
    parts.append("")

    if domain_parent_surface and domain_parent_surface.strip():
        parts.append("# This component presents")
        parts.append("")
        parts.append(
            "This is a **presentational** component. The domain "
            "components below are what it presents — the "
            "``domain_parent`` edges drawn at sysarch time say this "
            "component is a primary view into their content. Treat "
            "their technical specifications and public surfaces as "
            "read-only context: align your own ``<technical-"
            "specification>`` and ``<public-surface>`` with the "
            "shapes they already expose, and do not re-derive "
            "domain logic. If you need behavior that isn't on the "
            "domain side yet, declare a ``<dependency>`` on the "
            "domain component and lean on its public surface rather "
            "than duplicating its state into this layer.\n\n"
            "Some domain parents below include **two views**: the "
            "top-down technical specification / public surface "
            "(the **contract**, written before the impls pinned "
            "down the real shape) and a bottom-up fan-in "
            "synthesis (the **built reality**, articulated from "
            "the actual impls). If the two drift — operations on "
            "one side missing from the other, divergent shapes, "
            "invariants named in one view but not the other — "
            "align your presentational surface with the **built** "
            "view and call out the drift explicitly in your "
            "``<technical-specification>`` so the discrepancy is "
            "visible rather than papered over."
        )
        parts.append("")
        parts.append(domain_parent_surface.strip())
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
    elif feedback and prior:
        parts.append(
            "Revise the architecture doc to address the user feedback "
            "above. Preserve the decomposition where the feedback "
            "does not require a change. Output only the revised "
            "<comparch> block."
        )
    elif prior:
        parts.append(
            "Improve the architecture doc above. Fix any issues you "
            "notice with the techspec, public surface, subcomponent "
            "decomposition, or dependency structure. Output only the "
            "revised <comparch> block."
        )
    else:
        parts.append(
            "Write an initial architecture doc for this component "
            "based on its context above. Decide whether to decompose "
            "into subcomponents or stay un-fanned-out. Output only "
            "the <comparch> block."
        )

    return "\n".join(parts).rstrip() + "\n"
