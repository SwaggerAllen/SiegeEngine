# Catapult — Default bundle examples and flow sketches

**Status:** working file. YAML examples for tier, edge,
fragment, context, and flow declarations, plus the working
sketches for each of the default bundle's five flows. (The
scaffold's baseline behavior — generation from an approved
input doc with no active flow — is already illustrated end-
to-end by the Part 1 schema examples; it doesn't need its
own sketch.)

This file is reference content for the platform spec
(`catapult-spec-v3.md`) and the default bundle spec
(`catapult-default-bundle-v3.md`). Feature_expansion and
sysarch don't read it — examples and sketches burn tokens
during extraction without informing it. Bundle authors read
it; implementers read it; the platform's own components
attach it via `reference` edges from the default-bundle
feature node.

---

# Part 1 — Schema declaration examples

YAML sketches illustrating the four reactive-schema primitives
(tiers, edges, fragments, context) declared in platform spec
§A.3. Examples use the default bundle's tier and edge names
because they're concrete and recognizable; the same shapes
apply to any L2+ bundle.

## 1.1 Tier declaration

A tier declaration sets the tier's scope, identity, fields,
handle, and (optionally) draft grammar and generator.

```yaml
tiers:
  comp:
    scope: child_of(sysarch)
    identity: alias
    fields:
      name:       draft.name
      kind:       { from: draft.kind, enum: [domain, presentational] }
      role:       draft.role
      api_intent: draft.api-intent
    handle:
      fields:    [id, alias, name, kind, role, api_intent]
      fragments: [techspec, pubapi, privapi]
    # comp has no draft of its own — it's minted by sysarch's fanout;
    # its fragments are written by comparch via `produces:`
```

A tier without a `draft` produces no content of its own; it
exists purely as a join target. Most tiers have drafts.

## 1.2 Edge declarations

Five platform-level edge types: `fanout`, `reference`,
`dependency`, `policy_application`, `synthesis`. Bundles
declare named instances typed against one of these.

```yaml
- fanout:
    parent: sysarch
    child: comp
    property: draft.components
    cardinality: { child: { min: 1 } }

- reference:
    type: fulfills                              # comp → resp
    source: comp
    target: resp
    declared_in: comp.draft.responsibilities[].@id
    cardinality:
      source: { min: 1 }                        # every comp fulfills ≥1 resp
      target: { min: 1, max: 1 }                # every resp fulfilled by exactly 1 comp

- dependency:
    source: subcomp
    target: subcomp
    declared_in: comparch.draft.sub_dependencies[]
    from: @from                                 # resolves via subcomp.identity (alias)
    to:   @to
    scope: within(comparch)                     # both endpoints in same comparch's fanout
    graph_constraint: [acyclic, no_self_loop]
```

Cardinality endpoints use `{ min, max }` bounds. `{ min: 1,
max: 1 }` is exactly-one; `{ min: 1 }` is at-least-one;
`{ min: 0 }` is optional; `max: many` is the default.
Cardinality can be filtered (`when: kind == presentational`)
and scoped (`per_source(subreqs)`).

## 1.3 Context walks

A tier's `context:` is a list of typed edge walks its generator
reads. Each entry yields handles, fragments, or synthesis views.

```yaml
comparch:
  scope: per(comp)
  context:
    - self.parent.handle
    - self.parent.fulfills → resp.handle
    - self.parent.decomposed_by(subresp)
    - self.parent.dependency → target.handle.fragments[pubapi]
    - self.parent.domain_parent → target.synthesis
```

Context is the only readiness signal the scheduler needs. A
`(tier, scope)` pair is ready when every traversal in its
`context:` resolves to a ready source.

## 1.4 Fragment production

A tier can declare that its draft writes a fragment owned by a
different node:

```yaml
comparch:
  produces:
    - fragment: { owner: self.parent, kind: techspec, authored: draft.techspec }
    - fragment: { owner: self.parent, kind: pubapi,   authored: draft.pubapi }
    - fragment: { owner: self.parent, kind: privapi,  authored: draft.privapi }
```

This is how `comparch` populates its parent `comp`'s fragments
without `comparch` and `comp` being the same tier.

---

# Part 2 — Flow declaration sketches

Working sketches for each of the default bundle's five flows.
Each flow is a **schema delta** per platform spec §A.4: a
`flow.yaml` declaring additional tiers and edges the platform
grafts onto the scaffold, plus prompt files the flow-declared
tiers reference. (Scaffolding is not a flow; it's the
scaffold's baseline behavior with no delta active — see Part 1
for how the scaffold's tiers schedule themselves from an
approved input doc.)

Flows are sketched one at a time. Each sketch covers:

- **`flow.yaml`** — the schema delta: seed shape, direction,
  new tiers (planning tiers, phase-zero tiers), new edges
  into the scaffold.
- **Plan grammar** — the XML shape the planning tiers' drafts
  conform to.
- **Prompt files** — typically one shared `plan.md` Liquid
  template referenced by every planning tier in the flow,
  plus `phase-zero.md` where applicable.
- **Walked example** — what the LLM sees at a representative
  planning tier visit and the downstream scaffold tier regen.


## 2.1 Downward propagation

The platform's reactive scheduler would cascade staling-driven
regens through the dependent graph anyway; downward propagation
is kept as an explicit flow so the bundle ships an editable,
reviewable specification of "consume deferred feedback at these
nodes and propagate the implications downward." Mechanically
the thinnest of the five flows — no phase-zero, no structural
ops, no upward leg — and therefore the right starting sketch.

### 2.1.1 `flows/downward-propagation/flow.yaml`

```yaml
flow:
  name: downward-propagation
  seed:
    shape: node_set_with_feedback     # list of {node_id, feedback}
  direction: down
  parameters:
    max_depth:
      type: int
      default: null                   # null = walk to leaves
      description: |
        Optional cap on tiers below the seed the walk visits.
        Matches v2 §A.2.5's "propagate through comparch and
        subcomparch but stop before impl" use case.

# One planning tier per scaffold tier this flow visits. All
# reference the same ./plan.md. Bundle authors who need per-
# scaffold-tier prompt divergence point individual tiers at
# different files.
tiers:
  dp_plan_expansion:
    plans: expansion              # scaffold tier this plans for
    prompt: ./plan.md
    draft: { root: plan, grammar: ./plan-grammar.xml }
    context:
      seed_feedback: flow.seed.feedback_for(self.target)
      scope_handle: self.target.handle
      upstream_plan: self.target.parent.active_plan   # nil at seed

  dp_plan_reqs:
    plans: reqs
    prompt: ./plan.md
    draft: { root: plan, grammar: ./plan-grammar.xml }
    context:
      seed_feedback: flow.seed.feedback_for(self.target)
      scope_handle: self.target.handle
      upstream_plan: self.target.parent.active_plan

  # … dp_plan_sysarch, dp_plan_subreqs, dp_plan_comparch,
  #   dp_plan_subcomparch, dp_plan_impl, dp_plan_plan,
  #   dp_plan_code — same pattern, 9 planning tier declarations.

# Scope and edge semantics of `plans: <scaffold_tier>`:
#   - scope = per(scaffold_tier) with scope_filter ensuring the
#     target is in the flow's visit set (seed or implicated by an
#     upstream approved plan).
#   - establishes a 1:1 edge planning_tier → scaffold_tier, exposing
#     the plan handle as context.active_plan on the scaffold tier
#     regen when a flow is active. Idle: context.active_plan is nil.
```

The flow doesn't declare edges explicitly — the `plans:` field
on each planning tier implies both the scope and the edge
pattern. Platform reads `plans: expansion` as "one instance of
this planning tier per expansion node in the flow's visit set;
the plan handle lands on that expansion node's regen context as
`active_plan`."

### 2.1.2 `flows/downward-propagation/plan-grammar.xml`

Standard plan grammar, no `<structural-ops>` block (this flow
forbids them — plans auto-approve):

```xml
<plan>
  <intent>
    Brief prose describing what changes in this tier's regen
    given the seed feedback or upstream plan.
  </intent>
  <implicated-children>
    <child id="..." disposition="visit | skip | trivial">
      <rationale>...</rationale>
    </child>
    ...
  </implicated-children>
</plan>
```

Plans with only `<implicated-children>` auto-approve per
platform spec §A.4.6.

### 2.1.3 `flows/downward-propagation/plan.md`

Shared Liquid template. Every `dp_plan_*` tier references it.

````markdown
You are planning a regen of the {{ scope.target.tier }} node
at {{ scope.target.id }} as part of a downward-propagation
flow run.

{% if context.seed_feedback %}
# Seed visit — feedback to incorporate

Accumulated feedback on this node:

> {{ context.seed_feedback }}

Your task: plan a regen that incorporates the feedback, and
identify which children need to inherit the change.
{% else %}
# Downstream visit — inheriting an upstream change

The upstream {{ scope.target.parent.tier }} regen's plan was
approved. It implicated this node as a
`{{ context.upstream_plan.disposition_for(scope.target) }}`
visit because:

> {{ context.upstream_plan.rationale_for(scope.target) }}

Full upstream plan intent:

> {{ context.upstream_plan.intent }}

Your task: plan a regen that brings this node into line with
the upstream change, and identify which children need to
inherit it.
{% endif %}

# Context

{{ context.scope_handle }}

# Plan grammar

Produce a plan in the grammar below. Be precise about scope —
plans in this flow auto-approve, so the implicated-children
checklist you emit drives downstream scheduling directly.

For each child, choose a disposition:

- **visit** — the child needs to regenerate. Enqueued.
- **skip** — the child is unaffected; preserve existing content.
- **trivial** — the change reaches the child via a renamed
  field or reformatted text but produces no material content
  change. Preserve content; record the assessment.

Prefer **trivial** over **visit** when the material impact is
unclear. A follow-up downward-propagation flow can correct
misclassifications cheaply; over-scheduled regens can't be
uncreated.

You may NOT emit `<structural-ops>`. The platform will reject
the plan and re-prompt if you do. If a change requires
renaming, reparenting, merging, or splitting, the user is in
the wrong flow and should run a refactor instead.

```xml
<plan>
  <intent>...</intent>
  <implicated-children>
    <child id="..." disposition="visit | skip | trivial">
      <rationale>...</rationale>
    </child>
    ...
  </implicated-children>
</plan>
```
````

No per-tier conditionals needed — tier-specific framing comes
from `scope.target.tier` / `scope.target.parent.tier`
interpolation and from `context.scope_handle` (which renders
the scaffold tier's handle per its declaration). A bundle
author who wanted tier-specific guidance could add
`{% if scope.target.tier == 'comparch' %}…{% endif %}` blocks,
or split one of the `dp_plan_*` tiers off to point at a
different prompt file.

### 2.1.4 Scaffold tier regen with flow active

No new prompt file for regen. When the flow is active, each
scaffold tier's generation prompt sees `context.active_plan`
as an additional context entry. Scaffold tier prompts render
it conditionally:

```liquid
{% if context.active_plan %}
# Approved plan

> {{ context.active_plan.intent }}

The plan's intent is the scope contract for this regen. Don't
change fragments the plan didn't name. If the regen needs to
touch something the plan didn't anticipate, stop and indicate
the plan needs revision; the platform will fail back to
re-planning rather than silently expanding scope.
{% endif %}
```

Idle (no flow): `context.active_plan` is nil, the block
renders empty, the tier's generation prompt is its
from-scratch default. Flow-active: plan guidance is present.
One scaffold-tier prompt, two modes of use.

### 2.1.5 Walked example

User left feedback on `comparch_billing_abc`: "The public API
should expose `process_batch(invoices)`, not one-at-a-time
`process_one(invoice)`."

**Seed visit — `dp_plan_comparch` instantiates on
`comparch_billing_abc`:**

Liquid renders `plan.md` with:
- `scope.target.id = "comparch_billing_abc"`
- `scope.target.tier = "comparch"`
- `context.seed_feedback = "The public API should expose
  process_batch(invoices), not one-at-a-time
  process_one(invoice)."`
- `context.scope_handle = <the comparch's handle: name,
  kind, role, api_intent, fragments list>`
- `context.upstream_plan = nil` (this is the seed)

Plan output:

```xml
<plan>
  <intent>
    Replace the per-invoice public API
    (`process_one(invoice: Invoice) -> InvoiceResult`) with a
    batch endpoint
    (`process_batch(invoices: list[Invoice]) -> BatchResult`).
    The pubapi fragment changes; the techspec gains a note on
    batch semantics; the deps to BillingDb and TelemetryService
    remain. The subcomponent decomposition is unchanged.
  </intent>
  <implicated-children>
    <child id="subcomp_invoiceprocessor_xyz" disposition="visit">
      <rationale>InvoiceProcessor's pubapi receives invoices
        from comparch's API; the batching change shifts its
        input shape.</rationale>
    </child>
    <child id="subcomp_billingdb_xyz" disposition="skip">
      <rationale>BillingDb stores individual invoices;
        batching is upstream of its
        responsibility.</rationale>
    </child>
    <child id="subcomp_telemetry_xyz" disposition="skip">
      <rationale>TelemetryService unaffected by the batching
        choice.</rationale>
    </child>
  </implicated-children>
</plan>
```

Plan auto-approves. Platform sets `has_pending_flow_visit =
true` on `subcomp_invoiceprocessor_xyz` (scope_filter trigger
for `dp_plan_subcomparch`).

**Scaffold regen — `comparch_billing_abc`:**

The comparch generation prompt renders with
`context.active_plan` populated. The
`{% if context.active_plan %}` block includes the intent as
scope guidance. The LLM produces a new comparch draft scoped
to pubapi + techspec changes. Diff-reviewed, auto-approved.

**Downstream visit — `dp_plan_subcomparch` instantiates on
`subcomp_invoiceprocessor_xyz`:**

Liquid renders `plan.md` with:
- `scope.target.tier = "subcomparch"`
- `context.seed_feedback = nil`
- `context.upstream_plan = <the comparch plan above>`
- `context.upstream_plan.disposition_for(scope.target) =
  "visit"`
- `context.upstream_plan.rationale_for(scope.target) =
  "InvoiceProcessor's pubapi receives invoices from
  comparch's API; the batching change shifts its input
  shape."`

Planning proceeds. The walk eventually terminates at the leaf
impl, which regenerates a `git_commit`-tiered code diff; the
cascade ends.

### 2.1.6 What this validates / still to figure out

**Validates** the schema-delta model: the flow is entirely
expressible as a YAML declaration plus one Liquid prompt
file. No flow-specific runtime. Bundle author surface area
for adding downward-propagation is 3 files (`flow.yaml`,
`plan-grammar.xml`, `plan.md`).

**Validates** that per-scaffold-tier planning tiers stay
simple: 9 near-identical declarations in `flow.yaml`, all
pointing at the same prompt, differentiated only by which
scaffold tier they plan for. Trades a few lines of repetitive
YAML for explicit per-tier identity in the event log and
straightforward scope expressions.

**Still to figure out:**

1. **The `plans: <scaffold_tier>` syntactic sugar.** Need to
   pin down exactly how it desugars — what scope expression,
   what edge type, what `scope_filter` predicate for "target
   is in the flow's visit set." Probably fits in platform
   spec §A.3 (reactive-schema chapter) once a couple more
   flows are worked through.
2. **`context.upstream_plan.disposition_for(target)` and
   `rationale_for(target)` helpers.** The upstream plan's
   `<implicated-children>` structure needs convenience
   helpers the Liquid template can call. Worth spec'ing in
   A.4.5 alongside the base standard variable set.
3. **Multi-seed feedback ordering.** If two seed nodes have
   feedback and one is the ancestor of the other, the
   ancestor's regen affects the descendant before the
   descendant's seed visit fires. The descendant's seed
   feedback should be consumed at *its* seed visit, in
   addition to whatever the ancestor's plan implicated.
   Probably a note in A.4.10 about feedback consumption
   ordering.
4. **Regen scope-exceeds-plan detection.** The regen prompt
   says "stop and indicate the plan needs revision," but the
   mechanism for "regen detected scope creep" isn't spec'd.
   Options: rely on regen review catching it, or a regen-side
   validator comparing diff scope against plan intent. Worth
   nailing in A.4 once more flows are worked through.


## 2.2 Feature request

Seed is prose describing new capability the user wants
("add batch invoice processing"). A **phase-zero planning
tier** reads the prose plus the current `expansion` and
`sysarch` handles and produces the plan for `expansion`'s
regen — intent prose plus an additions list naming new
features to mint. The rest of the walk is structurally
identical to downward-propagation: one planning tier per
scaffold tier, all feeding the corresponding scaffold
tier's regen. The novel piece is the phase-zero entry
point that interprets prose seed into a structured
starting plan.

### 2.2.1 `flows/feature-request/flow.yaml`

```yaml
flow:
  name: feature-request
  seed:
    shape: prose
  direction: down
  parameters:
    max_depth:
      type: int
      default: null
      description: |
        Optional cap on tiers below expansion the walk
        visits. Use for preview runs that stop at sysarch
        to review architectural impact before committing
        subcomponent-level work.

tiers:
  # Phase-zero — the entry-point planning tier. Plans
  # the expansion regen from the user's prose seed.
  # Labeled "phase-zero" conceptually; mechanically it's
  # just a planning tier like any other.
  fr_plan_expansion:
    plans: expansion
    phase_zero: true                 # marker, informational
    prompt: ./phase-zero.md
    draft: { root: plan, grammar: ./plan-grammar.xml }
    context:
      seed: flow.seed                # the prose
      current_expansion: scope.target.handle
      current_sysarch:   scaffold.sysarch.handle

  fr_plan_reqs:
    plans: reqs
    prompt: ./plan.md
    draft: { root: plan, grammar: ./plan-grammar.xml }
    context:
      scope_handle:  scope.target.handle
      upstream_plan: scope.target.parent.active_plan

  fr_plan_sysarch:
    plans: sysarch
    prompt: ./plan.md
    draft: { root: plan, grammar: ./plan-grammar.xml }
    context:
      scope_handle:  scope.target.handle
      upstream_plan: scope.target.parent.active_plan

  # … fr_plan_subreqs, fr_plan_comparch, fr_plan_subcomparch,
  #   fr_plan_impl, fr_plan_plan, fr_plan_code — same pattern.
```

Two prompt files in this flow: `phase-zero.md` (entry-
point, reads the prose seed) and `plan.md` (every
downstream planning tier; reads upstream plan handle).
Bundle author could have a single shared file with
conditionals on `scope.target.tier` if they want fewer
files; separate files are clearer.

### 2.2.2 `flows/feature-request/plan-grammar.xml`

Extends the downward-propagation grammar with an
`<additions>` section — the regen at this tier is going
to mint new children not yet in scaffold, and the plan
needs to enumerate them so the review checklist and the
downstream scheduler both have something concrete to
latch onto.

```xml
<plan>
  <intent>
    Brief prose describing what this tier's regen will
    change, including any new children being minted.
  </intent>
  <additions>
    <child alias="batch_invoice_processing"
           name="Batch invoice processing">
      <rationale>New feature introduced by the flow's
        seed prose.</rationale>
    </child>
    ...
  </additions>
  <implicated-children>
    <child id="feat_existing_abc" disposition="visit | skip | trivial">
      <rationale>...</rationale>
    </child>
    ...
  </implicated-children>
</plan>
```

`<additions>` entries use aliases (not IDs) since the
children don't exist at plan time. The scaffold tier's
regen resolves aliases to minted IDs; downstream planning
tier instances see the resulting real nodes in their
context once the regen commits.

No `<structural-ops>` block — feature-request doesn't
propose renames / reparents / merges. Plans auto-approve.
A user who wants structural reshaping alongside the new
feature runs refactor instead (or runs feature-request
first and refactor after).

### 2.2.3 `flows/feature-request/phase-zero.md`

Entry-point prompt — reads prose seed and produces the
expansion regen's plan.

````markdown
You are the phase-zero planning tier for a feature-request
flow. The user has given you prose describing new
capability they want, and your job is to plan the
regeneration of the project's expansion node: decide
which features to add, and capture the shape of the
resulting expansion regen.

# User's request

{{ context.seed }}

# Current project state

## Feature expansion (current)

{{ context.current_expansion }}

## System architecture (current)

{{ context.current_sysarch }}

# Your task

Produce a plan in the grammar below. Your plan will drive
the expansion regen, which will mint new `feat_*` nodes
for each entry in your `<additions>` list and propagate
downward through the rest of the flow.

Guidance:

- Split the user's request into one or more distinct
  features if it implicates multiple concerns. "Add
  billing and invoice delivery" is probably two features,
  not one.
- Name features for the capability they introduce, not for
  the component they'd naturally live in. Downstream
  sysarch decides component boundaries.
- `<additions>` entries use aliases (not IDs) — the
  expansion regen assigns real IDs at mint time.
- `<implicated-children>` lists existing features this
  request modifies. Usually empty for pure additions; may
  have entries if the user's prose reframes or extends
  an existing feature.
- You may NOT emit `<structural-ops>`. If the user's
  request requires renaming / reparenting / deleting
  existing features, flag it in the intent and tell the
  user to run refactor instead.

```xml
<plan>
  <intent>...</intent>
  <additions>
    <child alias="..." name="...">
      <rationale>...</rationale>
    </child>
    ...
  </additions>
  <implicated-children>
    <child id="feat_..." disposition="visit | skip | trivial">
      <rationale>...</rationale>
    </child>
    ...
  </implicated-children>
</plan>
```
````

### 2.2.4 `flows/feature-request/plan.md`

Downstream planning tiers. Structurally parallel to
downward-propagation's `plan.md` — the downstream-visit
branch — with the framing adjusted for "new features are
entering the scaffold" rather than "feedback is being
consumed."

````markdown
You are planning a regen of the {{ scope.target.tier }}
node at {{ scope.target.id }} as part of a feature-request
flow run.

# Upstream plan

The upstream {{ scope.target.parent.tier }} regen's plan
was approved. It implicated this node as a
`{{ context.upstream_plan.disposition_for(scope.target) }}`
visit because:

> {{ context.upstream_plan.rationale_for(scope.target) }}

Full upstream plan intent:

> {{ context.upstream_plan.intent }}

New children minted upstream:

{% for addition in context.upstream_plan.additions %}
- `{{ addition.alias }}` — {{ addition.name }}
{% endfor %}

# Context

{{ context.scope_handle }}

# Your task

Produce a plan for this tier's regen given the upstream
changes. Identify:

- `<additions>` — new children this tier's regen will
  mint in response. For `reqs` seeing a new `feat_*`,
  this is new `resp_*` nodes. For `sysarch` seeing new
  resps, this may be new `comp_*` nodes (or existing
  comps getting new resps assigned, captured in
  `<implicated-children>`).
- `<implicated-children>` — existing children whose
  content changes. Use `disposition=visit|skip|trivial`
  as in downward-propagation (§2.1).

Prefer extending existing children over minting new ones
when the new capability fits an existing responsibility
or component. The user's request is phrased as capability
("batch invoice processing"), not as architecture — it's
this tier's job to decide whether that capability lives
in a new structural home or extends an existing one.

No `<structural-ops>`. Plans auto-approve.

```xml
<plan>
  <intent>...</intent>
  <additions>
    <child alias="..." name="...">
      <rationale>...</rationale>
    </child>
    ...
  </additions>
  <implicated-children>
    <child id="..." disposition="visit | skip | trivial">
      <rationale>...</rationale>
    </child>
    ...
  </implicated-children>
</plan>
```
````

### 2.2.5 Scaffold tier regen with flow active

Same mechanism as downward-propagation (§2.1.4). Each
scaffold tier's generation prompt picks up
`context.active_plan` and renders a
`{% if context.active_plan %}` block with the plan's
intent, additions, and implicated-children as regen
scope guidance.

The addition here: the scaffold tier's fanout now reads
the plan's `<additions>` to know which new children to
mint. For example, expansion's fanout over feat_*
children normally draws from `draft.features[]`; with a
flow active and a plan in context, expansion's regen
writes a draft whose `features[]` reflects the additions
from the plan, and normal fanout mints them.

### 2.2.6 Walked example (partial)

Seed: "add batch invoice processing — invoices should be
processed in bulk instead of one at a time, to support
high-volume customers."

**Phase-zero — `fr_plan_expansion` on the expansion
singleton:**

Liquid renders `phase-zero.md` with:
- `context.seed` = the prose above
- `context.current_expansion` = current expansion handle
- `context.current_sysarch` = current sysarch handle

Plan output (elided):

```xml
<plan>
  <intent>
    Add a "Batch invoice processing" feature to the
    project. The feature introduces bulk invoice
    handling as a first-class capability, with
    implications for high-volume customer support.
  </intent>
  <additions>
    <child alias="batch_invoice_processing"
           name="Batch invoice processing">
      <rationale>Direct expansion of the user's
        request.</rationale>
    </child>
  </additions>
  <implicated-children/>
</plan>
```

Auto-approves. Expansion regens, mints
`feat_batchinvoiceprocessing_abc123`.

**Downstream — `fr_plan_reqs` on the reqs singleton:**

Liquid renders `plan.md` with:
- `context.upstream_plan.additions` includes the new
  feat
- `context.upstream_plan.intent` reads through

Plan output (elided): adds new `resp_*` entries for
batch-throughput and batch-validation; implicates
existing billing-related resps for visit.

The walk continues through sysarch (assigning new resps
to an existing Billing comp), that comp's subreqs,
comparch, subcomparch, impl, plan, code.

### 2.2.7 What this validates / still to figure out

**Validates** phase-zero as a planning tier: `plans:
expansion` + `phase_zero: true` + context reading
`flow.seed` is all the mechanism needed. No special
runtime for phase-zero.

**Validates** `<additions>` in the plan grammar. The
scaffold tier's fanout reads additions at mint time;
aliases resolve to real IDs; downstream planning sees
minted nodes in context via the updated upstream handle.

**Still to figure out:**

1. **Partial-visit fanout.** When a plan has both
   `<additions>` and `<implicated-children>` with some
   children dispositioned `skip`, the scaffold tier's
   regen needs to write a draft that mints the
   additions but leaves skipped children unchanged.
   That's a property of the scaffold tier's draft
   grammar and regen prompt — straightforward, worth a
   note in A.4 about how regens compose plan outputs.
2. **Phase-zero-reads-sysarch dependency.** Phase-zero
   reads the current `sysarch` handle as context. What
   happens during scaffolding when sysarch isn't
   minted yet? Probably: feature-request is only valid
   against a project that has completed scaffolding up
   through sysarch. Enforce at flow-start: the flow
   lobby rejects feature-request if sysarch is missing
   or pending.
3. **Interaction with downward propagation of existing
   feedback.** If there's accumulated feedback on
   `sysarch` and the user kicks a feature-request, the
   fr_plan_sysarch plan ought to consider that feedback
   alongside the new feature. Either: feature-request's
   planning tiers read `scope.target.pending_feedback`
   as part of context, or: the user should run
   downward-propagation first to drain feedback, then
   feature-request. The second is the v2 behavior
   (one-flow-at-a-time lobby). Probably fine to keep;
   worth a UX affordance in the lobby that says "this
   node has pending feedback; consume it first?"
4. **Phase-zero context on bundle-agnostic terms.** The
   phase-zero declaration reads
   `scaffold.sysarch.handle` by name — that's a default-
   bundle-specific reference. A bundle without a
   `sysarch` tier would need a different reference.
   Phase-zero's context is genuinely bundle-specific,
   which means phase-zero prompts aren't portable across
   bundles. That's probably fine — phase-zero shapes
   the seed into the specific schema the bundle uses —
   but worth noting.

## 2.3 Refactor

Seed is prose describing a structural change the user wants
("extract the caching layer out of the billing service into
its own top-level component", "rename Policy to Rule
throughout"). A phase-zero planning tier reads the prose and
current expansion/sysarch, emits a plan whose `<structural-
ops>` list names the destructive operations to apply. Each
downstream planning tier inherits the structural-ops list as
upstream context and adds its own operations where relevant.
All operations queue through the flow; the platform applies
them in one transaction at end-of-run per v2 §A.2.3.

Every plan in this flow can carry `<structural-ops>`, so
every plan is **human-gated** per platform spec §A.4.6. The
bundle author doesn't set a flow-level "always gate" knob —
the gate falls out of the planning tier's grammar allowing
`<structural-ops>`.

### 2.3.1 `flows/refactor/flow.yaml`

```yaml
flow:
  name: refactor
  seed:
    shape: prose
  direction: down
  parameters:
    max_depth:
      type: int
      default: null
      description: |
        Optional cap on tiers below expansion the walk
        visits.

  # Refactor is the one flow whose planning gate is
  # always human; the gate actually falls out of the
  # plan grammar allowing <structural-ops>, but we
  # surface the flag here for UX affordances (the lobby
  # can warn "this flow human-gates every tier's plan").
  planning_gate_policy: always_human

tiers:
  rf_plan_expansion:
    plans: expansion
    phase_zero: true
    prompt: ./phase-zero.md
    draft: { root: plan, grammar: ./plan-grammar.xml }
    context:
      seed: flow.seed
      current_expansion: scope.target.handle
      current_sysarch:   scaffold.sysarch.handle

  rf_plan_reqs:
    plans: reqs
    prompt: ./plan.md
    draft: { root: plan, grammar: ./plan-grammar.xml }
    context:
      scope_handle:  scope.target.handle
      upstream_plan: scope.target.parent.active_plan

  rf_plan_sysarch:
    plans: sysarch
    prompt: ./plan.md
    draft: { root: plan, grammar: ./plan-grammar.xml }
    context:
      scope_handle:  scope.target.handle
      upstream_plan: scope.target.parent.active_plan

  # … rf_plan_subreqs, rf_plan_comparch, rf_plan_subcomparch,
  #   rf_plan_impl, rf_plan_plan, rf_plan_code — same pattern.

# End-of-run hook: after the walk terminates, apply every
# approved plan's <structural-ops> in a single transaction,
# in order (phase-zero first, then topologically). Ops are
# applied by the instruction-vocabulary reducer per §A.8.1.
end_of_run:
  apply_structural_ops: true
```

### 2.3.2 `flows/refactor/plan-grammar.xml`

Extends the feature-request grammar with a
`<structural-ops>` block. Each op has a `type` and
op-specific parameters. Op types match the platform's
instruction vocabulary (§A.8.1): rename, reparent, promote,
demote, merge, split, delete, plus per-edge-type
create/delete.

```xml
<plan>
  <intent>
    Prose describing the structural change at this tier
    and the reasoning for each structural op proposed.
  </intent>
  <structural-ops>
    <op type="rename" target="policy_abc123" new-name="Rule"/>
    <op type="promote" target="subcomp_caching_xyz"
        new-parent="null"/>                      <!-- to top level -->
    <op type="merge" targets="comp_x,comp_y" keep="comp_x"/>
    <op type="split" target="comp_billing"
        new-children="comp_billing_core,comp_billing_reporting"/>
    <op type="delete" target="feat_legacy"/>
    <!-- ... -->
  </structural-ops>
  <additions>
    <child alias="..." name="...">
      <rationale>Minted by the refactor (e.g., the
        extracted component).</rationale>
    </child>
    ...
  </additions>
  <implicated-children>
    <child id="..." disposition="visit | skip | trivial">
      <rationale>Existing child whose content changes
        because of the structural ops above.</rationale>
    </child>
    ...
  </implicated-children>
</plan>
```

Op enumeration is bundle-specific — the default bundle's
planning tiers accept the ops listed above because those
match the default's instruction vocabulary. An L3 bundle
with different structural operations would declare
different op types in its grammar.

Any non-empty `<structural-ops>` → **human-gated**. The
review UI renders the ops list as a line-item checklist
alongside the implicated-children checklist; reviewers can
strike individual ops without rejecting the whole plan.
Struck ops don't apply at end-of-run; struck plan
children don't enqueue.

## 2.4 Bug-fix propagation

To be sketched.

## 2.5 Upward propagation

To be sketched.
