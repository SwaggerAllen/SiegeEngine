# Catapult — Default bundle examples and flow sketches

**Status:** working file. YAML examples for tier, edge,
fragment, context, and flow declarations, plus the working
sketches for each of the default bundle's six flows.

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

Working sketches for each of the default bundle's six flows.
Each flow is a **schema delta** per platform spec §A.4: a
`flow.yaml` declaring additional tiers and edges the platform
grafts onto the scaffold, plus prompt files the flow-declared
tiers reference.

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
the thinnest of the six flows — no phase-zero, no structural
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

To be sketched.

## 2.3 Refactor

To be sketched.

## 2.4 Bug-fix propagation

To be sketched.

## 2.5 Upward propagation

To be sketched.

## 2.6 Scaffolding

To be sketched. Likely the simplest because it has no
phase-zero and no upstream context to merge — every visit
runs plan + regen against the tier's standard regen context
and the parent's plan, full stop.
