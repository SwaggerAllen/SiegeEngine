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
Each flow is declared per platform spec §A.4: a seed shape, an
optional phase-zero tier, a direction, and the per-tier
(planning, regeneration) prompt pair.

Flows are sketched one at a time. Each sketch covers:

- **Declaration YAML** — the bundle entry that names the flow
  and its parts.
- **Phase-zero tier declaration** (where applicable) — the
  bundle-declared singleton-per-flow-run tier with its scope,
  draft grammar, handle, and prompt template.
- **Plan grammar** — the XML structure planning prompts emit,
  including `<implicated-children>` and (where applicable)
  `<structural-ops>`.
- **Planning prompt template** — generic over tier; composes
  with tier-specific instructions from `scaffold/`.
- **Regeneration prompt template** — generic over tier.
- **Walked example** — a worked single-tier visit showing what
  the LLM sees and what it produces.

Open question to validate as we work through flows: the
generic-over-tier prompt composition. The bet is that
tier-specific framing (what does `comparch` produce; what's
its draft grammar for) lives on the tier declaration in
`scaffold/tiers/<tier>.yaml`, and the flow's plan/regen
prompts reference those fields generically. If sketching a
flow forces tier-specific copy into the flow prompt, the
composition needs revisiting.

## 2.1 Downward propagation

The platform's reactive scheduler would cascade staling-driven
regens through the dependent graph anyway; downward propagation
is kept as an explicit flow so the bundle ships an editable,
reviewable specification of "consume deferred feedback at these
nodes and propagate the implications downward." Mechanically
the thinnest of the six flows — no phase-zero, no structural
ops, no upward leg — and therefore the right starting sketch.

### 2.1.1 Declaration

```yaml
flows:
  downward_propagation:
    seed:
      shape: node_set_with_feedback     # list of {node_id, feedback}
    direction: down
    phase_zero: null                    # seed is already structured
    parameters:
      max_depth:
        type: int
        default: null                   # null = walk to leaves
        description: |
          Cap on tiers below the seed the walk will visit.
          Matches v2 §A.2.5's "propagate through comparch and
          subcomparch but stop before impl" use case.
    prompts:
      plan: flows/downward_propagation/plan.md
      regen: flows/downward_propagation/regen.md
    plan_grammar:
      structural_ops: forbidden         # this flow never proposes them
      implicated_children: required
    gating:
      planning: auto                    # never destructive
      regeneration: auto_unless_flagged
```

A few load-bearing fields:

- **`seed.shape: node_set_with_feedback`** — the seed is a list
  of `(node_id, feedback)` tuples, where `feedback` is whatever
  accumulated on the deferred-feedback queue for that node.
  Multi-seed: the platform processes seeds in topological order,
  so feedback on a parent is consumed before its children's
  visits inherit the regenerated parent.
- **`phase_zero: null`** — the seed is already structured;
  there's nothing to interpret before the walk starts. Most
  flows that consume feedback won't need phase-zero.
- **`plan_grammar.structural_ops: forbidden`** — declarative
  way to say "this flow's planning prompt can't emit
  `<structural-ops>` even if the LLM tries to." The platform's
  plan parser rejects such output, the flow falls back to
  re-planning. This is what makes the flow safe to auto-approve
  every plan; there's no destructive payload possible.
- **`gating.planning: auto`** — falls out of the structural-ops
  prohibition. Bundles can still set
  `gating.planning: always` for environments that want
  hand-review of every change, but the default is auto since
  there's no way for the plan to be destructive.

### 2.1.2 Plan grammar

Standard plan grammar minus `<structural-ops>`:

```xml
<plan>
  <intent>
    Brief prose describing what changes in this tier's regen
    given the upstream context (feedback at the seed visit;
    parent's plan otherwise).
  </intent>
  <implicated-children>
    <child id="comp_abc12345" disposition="visit">
      <rationale>The pubapi changes affect this child's
        dependency surface.</rationale>
    </child>
    <child id="comp_def67890" disposition="skip">
      <rationale>This child doesn't reach the changed
        method.</rationale>
    </child>
    <child id="comp_xyz98765" disposition="trivial">
      <rationale>The child references the changed name, but
        the regen would produce no material content
        change.</rationale>
    </child>
  </implicated-children>
</plan>
```

Three dispositions, each with explicit rationale that the
review UI surfaces as the editable effect-list checklist
(per platform spec §A.4.6).

### 2.1.3 Planning prompt — `flows/downward_propagation/plan.md`

```jinja
You are planning the regeneration of {{ tier.name }}
at {{ scope.id }}.

# What this tier does
{{ tier.purpose }}

# What this tier produces
{{ tier.output_summary }}

Its draft grammar produces:
{{ tier.draft.grammar_summary }}

# Why this regen is happening
This is a **downward propagation** flow run. {%
if seed_feedback -%}
This is the seed visit — accumulated deferred feedback was
left on this node and is being consumed.
{%- else -%}
This is a downstream visit — the parent tier's plan
implicated this child, and we're propagating the change.
{%- endif %}

{% if seed_feedback -%}
## Feedback to incorporate
{{ seed_feedback }}
{%- endif %}

{% if parent_plan -%}
## Upstream plan
The parent tier's plan has been approved. It implicated this
node as a `{{ parent_plan.disposition_for_self }}` visit
because:

> {{ parent_plan.rationale_for_self }}

Full upstream plan intent:

{{ parent_plan.intent }}
{%- endif %}

# Standard regen context for {{ tier.name }}
{{ tier.standard_context_rendering }}

# Your task
Produce a plan in the grammar below.

The `<intent>` should describe in 2–4 sentences what changes
in this tier's regen given the inputs above. Be specific
about which fragments / fields / sections are affected.

For each child of this node listed in the context, choose a
disposition:

- **visit** — the child needs to regenerate to incorporate
  the change. The platform will enqueue a downstream visit.
- **skip** — the child is unaffected; preserve its existing
  approved content. No work enqueued.
- **trivial** — the change technically reaches the child
  (e.g. it references a renamed field) but the regen would
  produce no material content change. Preserve existing
  content; the disposition is recorded in the audit trail.

Be conservative: prefer **trivial** over **visit** when the
material impact is unclear. A user can always kick a
follow-up downward propagation flow on the children that
turn out to need it.

You may NOT emit `<structural-ops>` in this flow — the
platform will reject the plan and re-prompt if you do. If a
change requires structural operations (rename, reparent,
merge, etc.), the user is in the wrong flow and should run a
refactor flow instead.

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
```

### 2.1.4 Regeneration prompt — `flows/downward_propagation/regen.md`

```jinja
You are regenerating {{ tier.name }} at {{ scope.id }}.

# What this tier does
{{ tier.purpose }}

# Why this regen is happening
This is a downward propagation flow run. The plan for this
regen has been approved:

> {{ plan.intent }}

{% if seed_feedback -%}
The plan was produced in response to feedback left on this
node:

> {{ seed_feedback }}

{%- endif %}

# Standard regen context for {{ tier.name }}
{{ tier.standard_context_rendering }}

# Prior approved content
The diff between your regen and the content below will be
what the reviewer sees:

```
{{ prior_content }}
```

# Your task
Produce a new draft for this tier per its grammar:

{{ tier.draft.full_grammar }}

The intent of the approved plan constrains what should
change. Don't introduce changes outside that scope — if the
regen needs to touch something the plan didn't name, stop
and the platform will fail back to re-planning rather than
silently expanding scope.
```

### 2.1.5 Walked example

User left feedback on `comparch_billing_abc`: "The public API
should expose `process_batch(invoices)`, not one-at-a-time
`process_one(invoice)`."

**Seed visit at `comparch_billing_abc`:**

Planning prompt sees:
- `tier.name = "comparch"`,
- `tier.purpose = "Comparch describes a component's tech spec, public API, private surface, dependencies, policy applications, and decomposition into subcomponents."`,
- `seed_feedback = "The public API should expose process_batch(invoices), not one-at-a-time process_one(invoice)."`,
- `parent_plan = null` (this is the seed),
- standard context: the comp's handle, its `fulfills` resps, its dep targets' pubapis, its subreqs.

Plan output:

```xml
<plan>
  <intent>
    Replace the per-invoice public API
    (`process_one(invoice: Invoice) -> InvoiceResult`) with a
    batch endpoint
    (`process_batch(invoices: list[Invoice]) -> BatchResult`).
    The pubapi fragment changes; the techspec gains a note
    about batch semantics; the deps to BillingDb and
    TelemetryService remain. The subcomponent decomposition
    is unchanged — InvoiceProcessor still owns per-invoice
    work, but its parent now hands it batches.
  </intent>
  <implicated-children>
    <child id="subcomp_invoiceprocessor_xyz" disposition="visit">
      <rationale>InvoiceProcessor's pubapi receives invoices
        from comparch's API. With the API switching to
        batches, the subcomp's input shape changes and its
        own pubapi has to follow.</rationale>
    </child>
    <child id="subcomp_billingdb_xyz" disposition="skip">
      <rationale>BillingDb stores individual invoices;
        whether it receives them one-at-a-time or in a
        batch is upstream of its
        responsibility.</rationale>
    </child>
    <child id="subcomp_telemetry_xyz" disposition="skip">
      <rationale>TelemetryService's pubapi is unaffected by
        the batching choice.</rationale>
    </child>
  </implicated-children>
</plan>
```

Plan auto-approves. Regen runs, produces a new comparch
draft with the updated pubapi. Regen auto-approves
(diff-reviewed but not flagged).

Platform enqueues one visit:
`(subcomp, subcomp_invoiceprocessor_xyz)`.

**Downstream visit at `subcomp_invoiceprocessor_xyz`:**

Planning prompt sees:
- `seed_feedback = null`,
- `parent_plan = the comparch plan above`,
- `parent_plan.disposition_for_self = "visit"`,
- `parent_plan.rationale_for_self = "InvoiceProcessor's pubapi receives invoices from comparch's API. With the API switching to batches, the subcomp's input shape changes and its own pubapi has to follow."`

Plan output (illustrative):

```xml
<plan>
  <intent>
    Update InvoiceProcessor's pubapi to accept a batch of
    invoices and produce a BatchResult. The internal
    decomposition stays the same — each invoice still
    routes through the per-invoice processing pipeline —
    but the entry point changes shape.
  </intent>
  <implicated-children>
    <child id="impl_invoiceprocessor_xyz" disposition="visit">
      <rationale>The implementation needs the new batch
        entry point and the per-item iteration that was
        previously the caller's
        responsibility.</rationale>
    </child>
  </implicated-children>
</plan>
```

Plan auto-approves; regen runs; impl visit enqueues; walk
continues until impl produces a code diff (one commit per
leaf via the `git_commit` generator) and the cascade
terminates.

### 2.1.6 What this validates / open questions

**Validates** the generic-over-tier composition: the
planning and regen prompts above don't have any tier-specific
copy. The tier-specific content comes from
`tier.purpose`, `tier.output_summary`,
`tier.draft.grammar_summary`, `tier.draft.full_grammar`, and
`tier.standard_context_rendering` — all of which are fields
on the tier declaration in `scaffold/tiers/<tier>.yaml`.
The flow prompts reference them by name. One plan template,
one regen template, used at every tier the flow visits.

**Implies** that tier declarations need additional metadata
fields beyond what platform spec §A.3.1 currently lists:

- `purpose` — 1–2 sentence prose describing what the tier is
  for. Authored once; reused everywhere.
- `output_summary` — 1–2 sentence prose describing what the
  tier produces.
- `draft.grammar_summary` — short prose summary of the draft
  grammar (for planning, where the LLM doesn't need the full
  grammar yet).
- `draft.full_grammar` — the canonical draft grammar (for
  regen, where the LLM has to produce parseable output).
- `standard_context_rendering` — the engine-rendered context
  per the tier's `context:` declaration, formatted as prose
  for the LLM.

These extend the tier-declaration schema in §A.3.1; they
should land in the platform spec as part of the reactive-
schema chapter once the prompt-composition design is
confirmed.

**Open questions:**

1. **Where does `parent_plan.disposition_for_self` come
   from?** The platform has to surface "the parent's plan
   implicated *me* with this disposition and rationale" as
   structured context. That's a small extraction over the
   parent plan's `<implicated-children>` list; routine but
   worth declaring in the platform spec's flow runtime
   section.
2. **What happens if regen exceeds the plan's scope?** The
   regen prompt says "stop and fail back to re-planning,"
   but the actual mechanism for "regen detected scope creep"
   isn't specified. Two options: rely on regen review
   catching it (human says "this changed too much, kick a
   re-plan"), or have a regen-side validator that rejects
   drafts whose diff scope exceeds the plan's intent. Worth
   nailing down later, doesn't block the sketch.
3. **Multi-seed feedback merge.** If two seed nodes have
   feedback and one is the ancestor of the other, the
   ancestor's regen will affect the descendant before its
   own seed visit fires. Probably the right answer is "the
   descendant's seed feedback is consumed at *its* seed
   visit, in addition to whatever the ancestor's plan
   implicated for it." Worth a note in the platform's flow
   runtime section about feedback consumption ordering.
4. **Conservatism bias in disposition choice.** The plan
   prompt encourages "trivial over visit when uncertain."
   Whether that's the right default is empirical — too
   conservative and changes get dropped silently; too
   liberal and downward propagation explodes the work
   queue. Worth instrumenting and tuning per tier in
   practice.

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
