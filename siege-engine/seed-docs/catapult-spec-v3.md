# Catapult — Specification (v3 — TOC draft)

**Status:** organizational proposal, not yet prose. Each leaf section
carries a one- or two-line stub describing what lands there and
(where applicable) which v2 section the content is inherited or
refactored from.

The central structural bet of v3 is that **Part A describes the
platform** — what Catapult does regardless of bundle — and **Part
B describes the default bundle**, the graph-of-prompts design
system that ships with Catapult for AI code generation. Part C
carries the implementation architecture (v2 Part B, moved and
otherwise unchanged).

The test for whether a topic belongs in A vs. B: if a different
bundle could change the paragraph's behavior, it's bundle content
and goes in B. If the paragraph stays true regardless of which
bundle is loaded, it's platform content and goes in A.

---

# Part A — Platform

## A.0 Vision

Catapult is a **design memory** system. It is not just a
documentation tool and not just a code generator — it is the
machine that holds the *why* behind every architectural
decision, the *shape* of every component boundary, and the
*history* of every revision. When an AI generates code, it
does so informed by the full context of human decisions that
preceded it. When a human reviews output, they see exactly
where it sits in the design hierarchy and what upstream
thinking produced it.

The core insight is that AI-generated code is only as good as
the design thinking that guides it. A single massive prompt
produces generic output. A structured graph of design
entities — features feeding responsibilities feeding component
architectures feeding plans feeding code — produces code that
reflects genuine design intent. Catapult maintains this graph
as a living artifact: event-sourced, reviewable, and always
the authoritative source of truth for what the system is and
why it was built that way.

This makes Catapult a *plan-before-you-code* machine. The
design graph isn't scaffolding to be discarded after
generation — it is the persistent design memory of the
project. Changes flow through it: new features are routed to
the right components, bug fixes propagate upward from affected
code, refinements cascade through dependent nodes. The
structured model evolves with the codebase because it *is* the
codebase's design substrate.

For teams, this means onboarding becomes reading the graph.
Architectural disputes become conversations anchored to
specific nodes. Code review starts with design review. The
system doesn't just generate — it remembers, and it holds
teams accountable to their own design decisions.

## A.1 What Catapult is

### A.1.1 Design memory, not a code generator or documentation tool

The distinction matters for every design decision that
follows. Catapult doesn't *produce* documentation as a side
effect of code generation; documentation is a rendering of the
same structured model the code is generated from. Catapult
doesn't *produce* code as a one-shot deliverable that the
design graph then discards; the graph is the persistent
substrate, and code generation is one of the rendering paths
off it.

The substrate is a **graph of typed nodes and typed edges**.
What kinds of nodes, what kinds of edges, how they decompose,
how they render into prose or code — all of those are
configured by the active **bundle**. The platform doesn't know
what a "component" or a "responsibility" is; it knows how to
hold a typed graph with reviewed content at each node and
deterministic projections from an event log.

The default bundle (Part B) ships a specific graph shape for
AI code generation — features decompose into responsibilities
which decompose into components, and so on. That shape is what
most users will encounter as "Catapult." But the shape is
bundle-owned; the platform's commitment is to hold whatever
graph the active bundle declares, with the invariants below
(A.1.2, A.1.3).

### A.1.2 The two platform commitments

Two load-bearing invariants define what Catapult *is* at the
platform level. Everything in Part A derives from one or the
other.

**The model is an event-sourced projection.** Every write is
an event appended to an ordered log; current state is
materialized by a reducer applying events in order. Rebuilding
state from the log must reproduce the same projection
byte-for-byte, and this is tested. There is no database
column that ever gets updated by anything other than the
reducer. "Revert" is "append the inverse event"; "undo" is a
query over the event log; "why does the graph look like this"
is answerable as a replay from any point in history.

**The scheduler is a reactive runtime over a typed graph
declared in a bundle.** The bundle declares tiers (node
kinds), edges (typed relationships), context walks (what each
tier reads at generation time), and predicates. The scheduler's
job is to evaluate, for every `(tier, scope)` pair, whether
its declared context has resolved to a ready state, and
enqueue generation when it has. The scheduler does not know
what a "component" is any more than the projection does — it
reads tier declarations and applies the same readiness rule
uniformly.

These two sentences are Catapult. The rest of Part A spells
out what they imply: how writes route through the reducer
(A.2, A.8), how the typed graph gets declared (A.3), how
generation is staged (A.4, A.5, A.7), how the lifecycle
composes (A.9), and the supporting infrastructure around it.

### A.1.3 Platform invariants vs. bundle invariants

The organizing principle for the rest of the spec is the
distinction between what the platform guarantees regardless
of bundle (platform invariants) and what a specific bundle
asserts when loaded (bundle invariants).

Platform invariants — true for every Catapult project, written
down concretely once in Part A — are the append-only event
log, the reducer-materialized projection, instructions as the
only write path (A.2.3), typed-schema reactive scheduling
(A.3), the one-flow-per-project lobby (A.9.1), the
draft-review-feedback-regen lifecycle (A.5), and flow-as-
schema-delta orchestration (A.4).

Bundle invariants are the specific tier vocabulary, edge
instances, fragment kinds, structural rules, flow
declarations, and generation order the bundle ships. They
hold for as long as the bundle is loaded; a different bundle
asserts different invariants. Part B describes the default
bundle's invariants in full.

The test for whether a statement belongs in Part A or Part B:
if changing the bundle could change the statement's behavior,
it's a bundle invariant and goes in B. If the statement is
true regardless of which bundle is loaded, it's a platform
invariant and goes in A.

## A.2 The structured model

### A.2.1 Events, reducer, projections

Every write to a Catapult project is an **event** — a
structured record with a type, a payload, a timestamp, and a
monotonically-increasing sequence number — appended to the
project's event log. The log is append-only; events are never
mutated or deleted. A **reducer** consumes events in order and
produces the **projection**: the set of nodes, edges,
fragments, drafts, and other derived state the rest of the
platform reads from.

The reducer is pure: given the same event sequence it produces
the same projection, byte-for-byte. This invariant is tested
exhaustively — the test suite reconstructs the projection from
each project's log and compares against the stored
projection. Any drift is a bug in the reducer, never in the
underlying state.

There are no duplicate-status fields on parallel tables that
could drift out of sync with the event log. The projection is
the only place state lives, and reverting a change is "append
events that undo the prior delta," never "reach into a table
and change a row." Fields computed from projection state are
queries against the projection, not stored state.

All writes go through a single **reducer entrypoint** that
validates the event, appends it to the log, and applies the
projection delta in one transaction. A failing validation
rejects the write atomically — no partial state lands. This
makes event emission the one chokepoint every mutation passes
through, which makes the reducer the load-bearing
correctness boundary and the test suite's primary target.

### A.2.2 IDs as opaque lineage markers

Every node in the projection carries a stable ID of the form
`<tier>_<8 Crockford base32 chars>`. The `<tier>` prefix is
the tier's declared name (from the bundle — `feat_*`,
`comp_*`, or whatever the bundle calls its tiers); the
suffix is opaque and random.

IDs don't encode names. A rename changes the node's name
field but not its ID. A node that's been renamed ten times
has the same ID it started with, and downstream references
continue to resolve. This is the point: IDs are for
**lineage**, names are for **intent**. The LLM and the UI see
both — IDs for stable reference, names for human
comprehension — and the platform treats them as independent
axes.

Singleton nodes (one-per-project tiers like an expansion or
sysarch bootstrap in the default bundle) use the same ID
shape. The 8-char suffix is decorative for a one-per-project
node, but uniform IDs mean uniform fragment keys, uniform
lookup tables, and no special cases at call sites.

An ID is stable for the lifetime of a node and gone when the
node is deleted. IDs are never reused. Lineage across rename,
promote, demote, reparent, merge, and split is tracked in the
event log — the sequence of events on an ID tells the whole
story of what happened to that node, not the name field's
current value.

### A.2.3 Instructions as the only write path

Nothing in Catapult mutates projection rows directly. Every
write to the graph goes through one of two channels:

- A **draft approval**. The generation pipeline produces
  drafts, reviewers approve them, and the approval emits
  events (typically `ContentCommitted` or similar) that the
  reducer projects into node content, fragment updates, and
  mint-derived children.
- A **structured instruction**. Rename, reparent, promote,
  demote, merge, split, create-edge, delete-edge, and similar
  operations are expressed as instructions — named events
  with validated payloads — that flow through the reducer
  the same way approvals do.

There is no text field anywhere in the UI that lets a user
type characters into a generated document and have those
characters become the stored content. Every change to
generated content goes through a **prose feedback →
regenerate → approve** cycle. A small set of structured UIs
exists for operations that are miserable to express in prose
(drag-drop assignments, edge editors, dependency graphs), but
those produce **prose instructions** that flow through the
regeneration pipeline on "apply," not direct state mutations.

This is what makes the event log sufficient. Because the
reducer is the only writer and instructions are fully
structured, any point-in-time projection is reconstructable,
any change is reviewable, and any "why" question is a replay
query. The channel discipline is what lets the rest of the
platform hold to the two commitments in A.1.2.

## A.3 The bundle as reactive schema

The load-bearing chapter. A.1.2 named two commitments; this is
where the second one — "the scheduler is a reactive runtime
over a typed graph declared in a bundle" — lands concretely.
The bundle is a **typed graph declaration**: tiers (node
kinds), edges (typed relationships), fragments (authored
sub-blocks), and context (what each tier reads from the graph
at generation time). Everything the scheduler does derives
from that declaration.

This framing collapses iteration, readiness gates, topology
conditionals, post-commit enqueues, and fan-in aggregation
into four declarative primitives plus a small predicate
language. The bundle's primary artifact, conceptually, is the
graph of tiers and edges; its YAML serialization exists so git,
LLMs, airgapped import, and text-first authoring all still
work.

### A.3.1 Tiers

A **tier** is a node kind in the generation graph. Each tier
declaration carries the following fields:

- **`scope`** — how instances of the tier attach to the graph.
  `singleton_under(X)` for one-per-X nodes; `per(X)` for
  per-parent-X instances; `child_of(X)` for tiers minted by a
  parent's fanout. The scope expression is what tells the
  scheduler how many `(tier, scope_parent)` pairs to enumerate
  for a given project state.
- **`scope_filter`** — an optional predicate narrowing the set
  of scope-parents this tier attaches to. E.g., "only
  fan-in-aggregate under parents whose kind is `domain` and
  which have at least one subcomponent." Predicate language in
  A.3.5.
- **`permitted_parents`** — a list when a tier attaches under
  more than one parent kind (e.g., policy tiers allowed under
  either a sysarch or a comp). Default is a single parent
  inferred from `scope`.
- **`identity`** — which field downstream references resolve
  against. `name`, `id`, or `alias`. Default is `id`; `alias`
  is what the default bundle uses for tiers that declare
  new entities before IDs exist (see Part B).
- **`fields`** — scalar values populated from the tier's draft
  via `draft.<path>` expressions. Fields are what appear on
  the node's projection row.
- **`handle`** — the public surface other tiers see. A named
  subset of fields plus a named subset of fragments. Whatever
  downstream tiers walk context edges to pull, they receive
  handle content, not raw draft content.
- **`draft`** — root tag + grammar for parsing LLM output.
  Omitted when the tier has no generation step (e.g., tiers
  that exist purely as join targets for edges).
- **`generator`** — the mechanism that produces the draft.
  `llm` (default), `git_commit`, `webhook`, `synthesis`, or
  other named generators the platform ships or the instance
  admin approves. See A.16 for `git_commit` specifically.
- **`context`** — an ordered list of edge-walk expressions
  declaring what the generator reads before producing a draft.
  See A.3.4.
- **`produces`** — optional declarations for fragments this
  tier's draft writes on other nodes (typically `self.parent`).
  See A.3.3.

A tier without a `draft` is a **join target** — it exists
purely so edges can terminate on it. Most tiers have drafts.

### A.3.2 Edges

Five platform-level edge **types**, each with its own
cardinality, graph-constraint, and readiness semantics:
`fanout`, `reference`, `dependency`, `policy_application`,
`synthesis`. The platform declares the type vocabulary;
bundles declare **named edge instances** typed against one of
these types, with particular source and target tiers.

- **`fanout`** — parent-creates-children; how every tier
  decomposes. A parent tier's draft property enumerates N
  children of a child tier, and the reducer mints them at
  parent approval.
- **`reference`** — general-purpose advisory-context edge,
  acyclic. Named pointer across tiers, resolved via the
  target's `identity`. Used for any "this node reads that
  node's handle" relationship that isn't a structural
  dependency.
- **`dependency`** — same-tier or cross-tier data dependency
  with `graph_constraint: acyclic` support. Stays
  platform-level because the cycle-detection machinery is
  platform-owned and non-trivial.
- **`policy_application`** — cross-cutting application of a
  policy node to a target, with reachability. The general
  "some nodes carry obligations that apply elsewhere" pattern
  is bundle-agnostic; specific policy kinds are bundle content.
- **`synthesis`** — reverse aggregation. A tier declared with
  `generator: synthesis` aggregates its children and publishes
  a handle that subscribers read via `reference`-style edges.
  The platform manages the first-pass readiness gate (fires
  once all children's required content is present) and the
  staling-on-subcomponent-change behavior; the bundle declares
  which tier does the aggregating and which tiers subscribe.

Every edge instance declaration carries: source tier, target
tier, `cardinality` on both endpoints, and `declared_in:` —
where in some tier's draft the edge gets emitted (e.g.,
`comp.draft.dependencies[].@to`). Cardinality endpoints use
`{min, max}` bounds; `{min: 1, max: 1}` is exactly-one,
`{min: 1}` is at-least-one, `max: many` is the default.
Cardinality can be filtered (`when: kind == presentational`)
and scoped (`per_source(subreqs)`). This single mechanism
replaces every named structural invariant — bijections,
coverage rules, partition properties — with uniform
bounded-count declarations.

Bundles instantiate edges by declaring concrete pairs of
source and target tiers against a type. The default bundle's
`domain_parent` edge is a named `synthesis` instance pointing
at the bundle's `fanin` tier; the default bundle's sibling-
dependency edge is a named `dependency` instance. See Part B
§2 for the default bundle's full edge catalogue.

### A.3.3 Fragments as authored-only content

A **fragment** is a named, authored prose block owned by a
specific node and readable by other tiers via
`handle.fragments`. Fragments let a node expose sub-chunks of
its content at finer granularity than the whole document —
a dependent tier might only need the target's public API
section, not its whole architecture doc.

Fragments are **authored only**. There is no "projected
fragment" category where the reducer derives fragment content
from other state. Every graph-derived view a prompt needs
is expressible as a `context:` edge walk at read time, which
makes materialization an engine-side caching decision rather
than a bundle concern. Serialization templates that would
render tuples back to inline XML do not appear in the bundle
DSL.

A tier can declare that its draft writes fragments owned by a
**different node**, typically its parent. This is what the
`produces:` mechanism is for: an architecture-doc tier might
declare `produces: [{owner: self.parent, kind: techspec,
authored: draft.techspec}, ...]` so the doc tier's draft
content lands as fragments on the parent node. Readers walking
context edges to the parent pick up those fragments without
knowing which tier authored them.

Fragment kinds are a closed vocabulary per bundle — the
default bundle declares `techspec`, `pubapi`, `privapi`,
`policies`, `deps` (see Part B §3). Adding a new fragment kind
is a bundle edit, not a platform change.

### A.3.4 Context walks

A tier's `context:` is an ordered list of typed edge walks its
generator reads before producing a draft. Each entry yields
handles, fragments, or synthesis views.

```
comparch:
  scope: per(comp)
  context:
    - self.parent.handle
    - self.parent.fulfills → resp.handle
    - self.parent.decomposed_by(subresp)
    - self.parent.dependency → target.handle.fragments[pubapi]
    - self.parent.domain_parent → target.synthesis
```

Context is the **only** readiness signal the scheduler needs.
A `(tier, scope)` pair is **ready** when every traversal in
its `context:` resolves to content in the *ready* state —
meaning the producing tier's instance is approved (for
authored content), or the underlying graph state has
stabilized (for projected views). Cardinality-many traversals
require *all* targets ready by default.

Two scheduling mechanisms that would otherwise need dedicated
platform machinery fall out of this rule:

- **First-pass synthesis gate.** A synthesis tier generates
  when every child's required content is approved. This is
  not a special predicate — it's the default "cardinality-
  many traversal requires all targets ready" applied to
  `self.parent.decomposed_by(child) → target.handle.content`.
- **Cross-tier subscription gate.** A presentational tier
  waiting for its domain parent's synthesis is just the
  context entry `self.parent.domain_parent → target.synthesis`
  failing to resolve until the synthesis tier's handle is
  populated.

Context declarations make scheduling **inspectable**. An
editor can render each tier's context as a dashed overlay
showing where a prompt's content comes from; missing or stale
sources are the complete set of things blocking a generation.

### A.3.5 Predicate language

Six operator families cover every conditional the platform
needs. Bundle authors use these in `scope_filter`,
`cardinality.when`, edge `constraint`, and edge
`graph_constraint`:

- **Comparison** — `==`, `!=`, `<`, `>`, `<=`, `>=`
- **Boolean** — `AND`, `OR`, `NOT`
- **Edge counting** — `has_edge(type)`, `count(edge_path) op N`
- **Existential** — `exists(edge_path where predicate)`
- **Universal** — `all(edge_path → field)`, `any(edge_path → field)`
- **Reachability** — `reaches(source, target, via=[edge_types])`

Field access is `self.field` for scalars,
`self.edge(type).target.field` for traversals, `self.parent`
for the scope-parent. Aggregates over traversals (`count`,
`any`, `all`, `exists`) are permitted; arithmetic, string
manipulation, and regex are not.

The predicate language appears in exactly four slots:

- **`scope_filter`** on a tier — restrict which scope-parents
  the tier attaches to.
- **`cardinality.when`** on an edge — restrict which nodes a
  cardinality bound applies to.
- **`constraint`** on an edge — value conditions on an edge's
  endpoints (e.g., `source.kind == presentational AND
  target.kind == domain`).
- **`graph_constraint`** on an edge — named structural
  invariants (`acyclic`, `no_self_loop`, `tree`).

**Named-predicate escape hatch.** A bundle that needs a
condition beyond the six operator families declares a name;
the instance admin approves the name at bundle import, and a
per-instance allowlist maps names to platform code. The name
appears in the bundle as if it were a built-in predicate. The
bundle itself contains no code. This preserves "bundles
learnable in an afternoon" while allowing the rare case that
genuinely needs computation.

### A.3.6 Scheduler as reactive runtime

The scheduler is three rules:

1. **Enumerate** every `(tier, scope_parent)` pair where
   `scope_parent` exists in the current projection and
   satisfies the tier's `scope_filter`.
2. **Evaluate readiness** — does every entry in the tier's
   `context:` resolve to a ready source?
3. **Enqueue** ready instances for generation, deduping on the
   `(tier, scope_parent)` key via the job queue's uniqueness
   constraint.

The scheduler is **state-driven**: readiness is a query
against the current projection, not a reaction to individual
events. This is what makes replay trivial — the same query
that answers "is this ready now?" also answers "was this
ready at time T?" by running against the projection state at
sequence number T. And it's what keeps the scheduler stateless
— no in-memory pending-set to corrupt, just a function from
projection state to enqueueable work.

Two triggers drive the readiness query in practice:

- **Fast path.** An event commits that plausibly changes some
  tier's readiness; the scheduler re-evaluates the affected
  `(tier, scope_parent)` pairs immediately. Wired through a
  per-project pub/sub channel.
- **Sweeper.** A low-frequency background loop (30–60s
  configurable) re-evaluates every enumerable pair against
  current state. Catches anything the fast path missed and
  provides an always-converging lower bound on correctness.

**Staling is the reactive dual.** When an approved node
changes (re-approval, content edit, force-reset), the
scheduler walks edges whose carried payload depends on the
changed slice and marks dependents stale. A stale tier
re-enters the readiness loop on the next poll; if its context
is still ready (or re-resolves after upstream regens), it
generates again. Staling doesn't bypass review — a stale
tier's next generation is a new draft that goes through the
same approval lifecycle.

Flow-aware behavior (A.4) adds one twist: when a flow is
active, the scheduler runs against the merged `scaffold ∪
flow` DAG rather than the scaffold alone. The three rules
above are unchanged; the enumerated pairs just include the
flow's planning tiers, and context walks see the flow's
added edges.

## A.4 Flows

Flows are **schema deltas** — additional tiers and edges a
bundle grafts onto the scaffold when a flow is active. The
platform merges them (`active_dag = scaffold ∪ flow`), the
reactive scheduler runs against the merged DAG, and the
flow ends when no more `(tier, scope)` pairs are
enqueueable. Two **walk-algorithm primitives** the scheduler
implements — `downward_cascade` and `up_then_down` — are
selected per flow via an `invokes:` hook in the flow's
declaration. Walk, gating, and prompt sequencing all fall
out of the merged schema plus the selected primitive.

### A.4.1 Flows as schema deltas

Each flow lives in `flows/<flow-name>/flow.yaml` plus its
prompt files. The YAML declares:

- a **seed** shape (prose input, code diff,
  node-set-with-feedback, …),
- an **`invokes:`** hook naming the walk-algorithm
  primitive (see §A.4.3),
- optional **preconditions** — predicates over current
  scaffold state evaluated before the lobby kicks the flow
  (see §A.4.10),
- new **tiers** — typically planning tiers whose output is
  consumed as context by scaffold tier regens, plus
  phase-zero tiers where the seed needs interpretation
  before the walk starts,
- new **edges** — connecting flow-added tiers to the
  scaffold, including which scaffold tiers read which
  planning outputs.

At flow start the platform computes the merged DAG.
Planning tier instances instantiate per scope; scaffold
tier regens find planning handles in their merged context
and consume them. At flow end the delta unmerges and the
scaffold returns to baseline. Cancelling an in-flight flow
discards unmerged pending visits.

### A.4.2 Planning tiers

A **planning tier** is a flow-declared tier whose draft
grammar emits a plan — prose intent plus structured
`<implicated-children>` and (for some flows) other
elements like `<additions>`, `<structural-ops>`, or
`<assessment>` (see §A.4.6 for grammar annotations and
gating).

Convention: one planning tier per scaffold tier the flow
visits, each referencing the same prompt file. Distinct
tier identities per scaffold tier give each plan its own
event-log id and keep scope expressions simple
(`scope: per(expansion)`, `per(sysarch)`, …). Bundles
that want per-scaffold-tier prompt divergence point
individual planning tiers at different files.

Two declarative-sugar fields on planning-tier declarations:

- **`plans: <scaffold_tier>`** expands to `scope:
  per(<tier>)` + a `scope_filter` that ensures the target
  is in the flow's visit set (seed nodes, plus
  `disposition=visit` implicated children, plus
  `<additions>` entries from approved upstream plans) + an
  implicit 1:1 reference edge exposing the plan handle as
  `context.active_plan` on the scaffold tier.
- **`leg: upward | downward`** — only meaningful under
  `invokes: up_then_down`. Tells the primitive which tiers
  to walk in which direction (see §A.4.3).

Planning tiers participate in normal readiness gating:
their `context:` declaration lists what they read, and the
scheduler enqueues them when context resolves. Scaffold
tier regens find the corresponding planning handle in
their merged context; the scaffold tier's generation
prompt is unchanged from baseline — it just has an
additional context entry to reason over. No separate
"regen prompt" per flow.

### A.4.3 Walk primitives: `downward_cascade` and `up_then_down`

The scheduler implements two walk algorithms. Flows select
one via `invokes:` in the declaration. Primitives ship no
default tier declarations — each flow declares its own
planning tiers; the primitive reads the flow's declaration
and applies its walk semantics.

**`downward_cascade`.** Standard forward walk. Seeds land
at declared planning tiers; next-wave visits are enqueued
from approved plans' `<implicated-children>` (and minted
from `<additions>` where the flow's grammar allows them).
Used by feature-request, refactor, downward-propagation.

**`up_then_down`.** The upward leg's `leg: upward`
planning tiers invert scaffold structural edges in their
context walks — a planning tier at `comp` reads its
subcomps' handles rather than its parent's. Upward-leg
planning produces artifacts at each ancestor up to project
root; merge-at-parent is automatic because multiple upward
instances converging on the same parent share that
parent's planning tier. Once the upward-leg work queue
drains (pivot detection at root), the downward leg runs
normally — planning + regen at each visited tier,
implicated-children fans out sideways, downward-leg plans
drive scheduling. Used by bug-fix-propagation,
upward-propagation. Split is always a downward-leg
concern; the upward leg narrows to the seed-to-root spine.

Bundle authors needing finer-grained edge inversion
express it directly in flow YAML edge declarations; the
`leg:` field is the shortcut for "this planning tier walks
scaffold structural edges in reverse."

### A.4.4 Phase-zero is just a planning tier

Flows whose seed needs interpretation declare a **phase-zero
planning tier**: singleton-per-flow-run, fires once. Its
context reads the seed plus platform-level scaffold
handles (typically `expansion` and `sysarch` — "here's
what this project already is, now shape this input into
work against it"). Downstream planning tiers read
phase-zero's handle like any other upstream dependency.
No special machinery — it's a tier.

### A.4.5 Prompt templating with Liquid

Prompt files are **Liquid templates** rendered at prompt
time. The platform guarantees a standard variable set
across every prompt:

- `scope` — the node being generated. `scope.id`,
  `scope.tier`, `scope.parent`, `scope.fields.*`,
  `scope.prior_content`.
- `context` — a map of named context entries resolved from
  the tier's `context:` declaration. Bundles walk into it
  (`context.feedback`, `context.upstream_plan`, …) based
  on the names their context entries define.
  `context.upstream_plan` exposes the upstream plan's
  parsed XML as dotted Liquid fields (intent, children,
  additions, structural_ops, assessment,
  disposition_for(target), rationale_for(target)).
- `flow` — metadata about the active flow: `flow.name`,
  `flow.run_id`, `flow.parameters`, `flow.seed`. Nil when
  no flow is active. `flow.seed.<accessor>(arg)` is
  seed-shape-routed: `node_set_with_feedback` gets
  `feedback_for(node)`; `code_diff` gets
  `diff_for(territory)`.
- `scaffold` — each scaffold tier exposes a handle under
  `scaffold.<name>` and may host platform-computed
  accessors (e.g., `scaffold.manifest.resolve_paths(diff)`
  for territory resolution).

Most prompts use only variable substitution
(`{{ scope.id }}`, `{{ context.feedback }}`). Liquid's
conditional blocks (`{% if scope.tier == 'comparch'
%}...{% endif %}`) are an escape hatch for per-tier
customization in a shared prompt file without splitting.
Document the hatch; don't require it.

The LLM never sees Liquid — the platform renders templates
before dispatch.

### A.4.6 Plan grammar annotations and gating

"Approval gates only destructive operations" (A.8.2 / v2
§A.3.3) is a grammar-level rule in the schema-delta model.
Two grammar annotations extend it:

- **`gate: always`** — a grammar element declaring this
  annotation gates plan approval whenever that element is
  present and non-empty, regardless of what else the plan
  contains. `<structural-ops>` carries this by default
  (destructive-op gating). `<assessment>` carries it in
  the upward-leg grammars used by upward-propagation and
  bug-fix-propagation, because the assessment is itself
  the reviewable payload.
- **`<no-change/>`** — a plan element signaling "no
  revision at this tier." The scaffold tier's regen
  elides when the plan carries it. Useful for upward-leg
  trivial assessments at ancestors well above the
  feedback origin and any flow that wants a "pass
  through" per-tier option.

**Structural ops apply immediately on plan approval** —
not deferred to end-of-run. Each tier's regen sees the
post-op state as current. This keeps refactor's regens on
the same semantic footing as every other flow's: plan
approved → ops applied → regen sees the new state.
Rollback-of-a-past-op is an inverse refactor, not a flow
cancel.

### A.4.7 Review UX invariants

Consistent across flows and bundles:

- **Plan review surfaces the effect set.** The
  `<implicated-children>` list renders as an editable
  visit/skip/trivial checklist with per-child rationales.
  Raw plan prose and structural-ops sit behind a "show
  reasoning" toggle.
- **Regen review is a diff.** Every regen presents as a
  diff against the prior approved content, never a
  full-document re-read. Per-fragment diffing falls out of
  the fragment model (A.3.3).

Both invariants fall out of the draft grammar's shape —
grammars with `<implicated-children>` render as
checklists; grammars extending prior content render as
diffs.

### A.4.8 Abstract flow catalogue

Stated bundle-agnostically; default-bundle instantiations
live in `catapult-default-bundle-v3.md` §10 with per-flow
sketches in `catapult-default-bundle-v3-examples.md` §2.

Scaffolding is *not* in the catalogue — it's the platform's
baseline behavior when no flow is active. A newly-created
project with an approved input doc runs the scaffold's
reactive scheduler directly; no schema delta, no `invokes:`.
The five flows below are the schema deltas bundles ship
for operations the scaffold can't do alone.

- **Feature request** — seed: feature-shaped prose;
  phase-zero shapes it into a feature list; invokes
  `downward_cascade`; grammar allows `<additions>`.
- **Refactor** — seed: structural-op prose; phase-zero
  surfaces the structural-ops list; invokes
  `downward_cascade`; grammar allows `<structural-ops>` —
  plans carrying ops are human-gated; ops apply
  immediately on approval.
- **Bug-fix propagation** — seed: code diff mapped to
  `git_commit`-owning leaves via
  `scaffold.manifest.resolve_paths` (A.16); invokes
  `up_then_down`; no new code generated.
- **Downward propagation** — seed: node-set-with-feedback;
  invokes `downward_cascade` with default prompts;
  reference implementation of the cascade pattern. Kept
  as a declared flow rather than folded into a platform
  action so bundles ship a worked example of feedback
  consumption.
- **Upward propagation** — seed: node-set-with-feedback;
  invokes `up_then_down` with default prompts; reference
  implementation of the up-then-down pattern bug-fix uses
  with a different seed.

### A.4.9 Flows and deferred feedback
Deferred feedback accumulates; flows consume. Refactoring
of v2 §A.2.7, referencing the catalogue in A.4.8. Downward
and upward propagation have feedback as their explicit
seed; other flows consume feedback on nodes they visit as
a side effect.

### A.4.10 Flow lifecycle: preconditions, multi-seed ordering, lobby composition

Three lifecycle rules that apply to every flow:

- **Preconditions.** Each `flow.yaml` declares a
  `preconditions:` list — predicates over current scaffold
  state evaluated before the lobby kicks the flow.
  Preflight failure surfaces in the lobby UI.
- **Multi-seed topological ordering.** When a flow's seed
  set includes nodes in ancestor/descendant
  relationships, seeds process in topological order:
  ancestor's plan and regen commit before the
  descendant's seed visit fires. Descendant's
  seed-feedback is consumed at its own seed visit on top
  of whatever the ancestor's plan implicated.
- **One-flow-per-project lobby rule** (A.9.1). At most one
  active flow, so the merged DAG is well-defined at any
  moment. Flows don't bypass readiness — the merged DAG's
  reactive scheduling is all the platform does. When an
  active flow ends its schema delta unmerges and the
  scaffold returns to baseline.

## A.5 Review, feedback, approval

Every artifact the system produces — any tier's draft,
fragment, plan, code diff, change plan — goes through review
before its content lands in the projection. Review is the
pipeline's discipline gate: the place where reviewer judgment
shapes the LLM's output, where accumulated feedback gets
consumed, and where the platform's invariant "approval is
the only way content commits" is enforced.

Two review surfaces exist — model-artifact review (markdown-
style rendering with inline + summary comments, diffs,
feedback panel) and code review (file-level diff, inline
review comments, CI status) — but both use the same
underlying status model and workflow. Which tiers use which
surface is a bundle decision; the lifecycle and feedback
machinery is the platform's.

### A.5.1 Draft → AI self-review → human review → approve

The base lifecycle all reviewable tiers share. Status
transitions:

```
pending → generating → ai_reviewing → awaiting_review → approved
                                                     → rejected
                                                     → stale
```

- **Generating.** The tier's generator (LLM, by default)
  produces a draft against its declared context and prompt.
- **AI self-review.** The draft runs through a short
  self-review pass against structured criteria (quality
  score, recommendation, notes). If the self-review
  recommends revision, the platform regenerates
  incorporating the self-review feedback, up to a
  configurable loop limit. See A.5.2.
- **Awaiting review.** After AI self-review, the draft
  enters human-review state. Reviewers leave **inline
  comments** anchored to specific sections or fragments,
  and **summary feedback** for cross-cutting concerns.
- **Approved.** Reviewer accepts. The approval event lands
  through the reducer and the draft's content commits to
  the projection.
- **Rejected.** Reviewer rejects with feedback (inline +
  summary). The platform regenerates the draft incorporating
  the feedback.
- **Stale.** Upstream context changed after approval.
  Regeneration is enqueued; the current content remains as
  fallback until the new draft approves.

Code tiers add a `ci_validating` step after `ai_reviewing`:
CI runs against the generated diff, and failure treats the
generation as "wrong" rather than "needs fixing" — the
generator retries with CI output as additional context. See
A.5.5 for the full code-tier chain.

### A.5.2 AI self-review

Every draft-producing tier has a second LLM pass that
critiques the generator's output against the same context
the generator saw. Reviews are **advisory only** — approving
a draft doesn't wait on review completion, and a failed
self-review doesn't block human approval.

The review pass is **automatic** after every draft commit,
gated off only by explicit project-level configuration (the
full-bootstrap-chain integration test disables it to avoid
doubling CLI call counts in CI).

Review storage is per-tier: the review text lives on the
draft row for draft-based tiers, or on the node row for
tiers that commit content directly without a draft cycle.
Re-generation cancels in-flight reviews — the new draft
starts with empty review text.

Review prompts follow the same Liquid-template model as
any other generator prompt (A.4.5); they're declared in
the bundle's tier spec alongside the main generation
prompt. The review output is itself a draft that goes
through the retry loop for transient CLI failures but
doesn't re-enter human review — reviews are advisory and
commit immediately on LLM success.

### A.5.3 Deferred feedback

Users can leave inline comments and summary feedback on
**any node at any time**, not just nodes currently awaiting
review. This feedback accumulates as pending and is included
automatically in the prompt context the next time the node
is regenerated.

Deferred feedback is the lightweight alternative to kicking
a full flow every time someone notices something. Working
deep in the tree reveals that an upstream node should
incorporate a new consideration; a user leaves a comment on
the upstream node and moves on. The comment waits until the
next flow touches that node, at which point the regen picks
it up. Deferred feedback does not trigger regeneration on
its own — it waits until consumed by a flow.

The dedicated consumption flows are the default bundle's
downward-propagation and upward-propagation flows (A.4.8);
any other flow that touches a node with pending feedback
consumes it incidentally.

**Comment lifecycle.** All comments can be edited or
deleted by their author after posting. Edits and deletions
are recorded in the event log (original content preserved
in history, not destroyed). Comments already consumed by a
regen are marked as such; deleting a consumed comment does
not undo the regen it influenced. Pending comments can be
freely edited or deleted until a flow picks them up.

**Feedback visibility.** Each node displays a pending
feedback counter. Counters roll up through parent edges —
a collapsed parent shows the sum of its own pending
feedback plus its descendants'. This gives an at-a-glance
view of where attention has accumulated across the tree.

### A.5.4 Collaborative discussions

Two conversation modes share the platform's chat
infrastructure (see A.13):

- **Private AI chat** — per-user, per-project. A user
  converses with the AI about the project; the thread is
  visible only to that user.
- **Team discussions** — threaded conversations attached to
  a specific artifact during review. Team-visible; members
  with artifact access participate. Messages are attributed
  to their author. Members can @-mention the AI in a thread
  and it responds in-thread with citations, visible to all
  participants. Discussion threads can culminate in review
  actions (approve, reject with feedback, request changes).

Team discussions persist alongside the artifact's review
history and become part of the artifact's provenance trail.
Future reviewers and the AI itself can reference prior
discussions to understand why decisions were made.

### A.5.5 Status chains

Explicit transitions for the two surface types.

**Model artifacts:**

```
pending → generating → ai_reviewing → awaiting_review
                                    → approved | rejected | stale
```

**Code artifacts:**

```
pending → generating → ai_reviewing → ci_validating → awaiting_review
                                                    → approved | rejected | stale
```

`ci_validating` is specific to tiers using the `git_commit`
generator (A.16). CI failure cycles back to `generating`
with error output as additional context, up to a retry
limit. Projects without CI configured skip the state
entirely.

Rejecting any artifact marks its downstream dependents
`stale`, which the reactive scheduler (A.3.6) picks up as
regen candidates on the next readiness sweep.

### A.5.6 Review granularity and batching

Review gates are configurable per project: per-node,
per-tier, leaves-only, or fully automatic with the
destructive-operation carve-out (A.8.2) as a hard override
no project setting can bypass. The default is sensible —
review fan-out and destructive ops, auto-approve everything
else at the node level — but the user controls it.

The intended workflow is **batched**: a flow run produces
N artifacts, pauses for human review of that batch, the
reviewer reads and leaves feedback on some or all of them,
rejected artifacts and their downstream dependents
regenerate as a sub-run incorporating the feedback, and
once the sub-run completes the parent flow resumes with
the next batch. Produce–review–regenerate–resume is the
cycle the lifecycle optimizes for.

### A.5.7 Restart semantics

Flow runs support four restart granularities:

- **Node-level** — regenerate a single node's output;
  downstream nodes are marked stale and the scheduler picks
  them up.
- **Tier-level** — restart every instance of a tier (e.g.,
  regenerate every component-architecture doc).
- **Flow-level** — restart the whole flow from the seed.
- **Partial retry** — retry only failed or rejected nodes
  within a tier, leaving approved nodes intact.

Each restart option names what gets invalidated in the UI
so the user knows what they're signing up for.

## A.6 Ownership and scoped roles

### A.6.1 Ownership as a scoped role
v2 §A.5.4 and §A.14.2. Stated abstractly — an owner holds the
`owner` role with scope pinned to a node ID. Scope-parent
traversal rules are platform-level.

### A.6.2 Permission atoms and roles
v2 §A.14.1, §A.14.3.

### A.6.3 Review routing and SLA
v2 §A.5.4 tail.

## A.7 Projection sources

### A.7.1 Bootstrap nodes
Authored prose that mints structured children on approval.
From v2 §A.4.1, §A.4.2. Platform-level mechanism; which tiers are
bootstraps is a bundle decision.

### A.7.2 Mint determinism from approved content
Parsing → event emission → reducer projection must be
deterministic. From v2 §A.4.

## A.8 Structural operations

### A.8.1 Instruction vocabulary
Rename, reparent, promote, demote, merge, split, per-edge-type
create/delete. From v2 §A.1.3 tail and §A.4.
Bundle-parametric — a bundle declaring new tiers inherits the
instruction families automatically.

### A.8.2 Approval gates on destructive operations
v2 §A.3.3.

### A.8.3 Fan-out pauses for review
v2 §A.3.4.

## A.9 Flow lobby and concurrency

### A.9.1 One active flow per project
v2 §A.6, §A.7.

### A.9.2 AI as read-only proposer
v2 §A.6.2.

### A.9.3 Resumability and recoverability
v2 §A.8.

## A.10 Document storage model

v2 §A.9.

## A.11 Bundles (configuration system)

### A.11.1 What a bundle is
A schema plus the prompts, grammars, and named generators the
schema references. New — consolidates scattered v2 §A.11.1 and
§A.11.2 opening.

### A.11.2 Bundle repositories and mirror-based approval
v2 §A.11.2 (curation/security subsection).

### A.11.3 Per-project overrides
v2 §A.11.3.

### A.11.4 Instance bundle library
v2 §A.11.2 (library subsection).

### A.11.5 Bundle-shipped reference material
v2 §A.11.2 tail. Calls into Part B §B.8 for the `ref_*` tier
the default bundle uses to hold such material.

### A.11.6 Named predicates and named generators
Escape hatches — v2 §A.11.6 escape-hatches subsection.

### A.11.7 What's still TBD (schema migration, override syntax)
v2 §A.11.7.

## A.12 Credentials and token tracking

v2 §A.12.

## A.13 Real-time updates and external integration

v2 §A.13 (SSE live updates, webhooks, external API).

## A.14 Authentication and identity

v2 §A.14.4, §A.14.5 (sessions, SSO). Permission atoms and roles
moved to §A.6.

## A.15 Multi-project support

v2 §A.15.

## A.16 Code delivery substrate and the `git_commit` generator

v2 §A.10 reframed around the `git_commit` generator type
declared in A.3.1. The substrate (gitea, forge plugins, branch
model, PR granularity, blocking-PR rule) is platform-level; any
tier whose bundle declaration picks `generator: git_commit`
inherits it.

### A.16.1 The `git_commit` generator contract
On approval of a tier instance using this generator, the platform
produces a commit whose scope is the instance's declared
territory (a `{repository, folder}` tuple, addressable by the
tier's fields), on the branch the active flow run owns, under
the blocking-PR rule. One commit per instance of any tier using
`git_commit`. Territory becomes platform-level because the
substrate needs it; the *shape* of the territory (folder on
disk) is bundle-level — the default bundle's `impl` tier maps
territory to folders (B.6), but a bundle shipping documentation
deliverables could map to files, and a bundle shipping binary
artifacts could map differently.

### A.16.2 Local gitea substrate
v2 §A.10.1.

### A.16.3 External forge integration via plugin adapters
v2 §A.10.2.

### A.16.4 Branch model, PR granularity, blocking-PR rule
v2 §A.10.4, §A.10.5, §A.10.6 — all platform-level, part of the
`git_commit` contract.

### A.16.5 Git is only for code, not for design
v2 §A.10.7.

## A.17 Admin and governance

v2 §A.21, §A.22.

## A.18 AI sandboxing

v2 §A.18.

---

# Part B — Default bundle

The platform ships with a **default bundle**: a graph-of-prompts
design system for AI code generation. It takes a prose input
document describing a project and produces a layered structured
model — features, responsibilities, components, subcomponents,
implementations, plans, code — through a reviewable pipeline.
Every node in the model is a reviewed artifact; every edge in
the model is a typed declaration the reducer projects from
approved fragment content.

The default bundle is what most users will encounter as
"Catapult." It exercises every platform mechanism: tier-and-edge
schema (Part A §A.3), per-tier reactive scheduling (§A.3.6),
flows that walk the graph with planning and regeneration
prompts (§A.4), `git_commit`-generator-driven code delivery
(§A.16), draft-and-review lifecycle (§A.5), ownership and
scoped roles (§A.6). Bundle authors who want a different
layered design system can fork the default bundle, swap tier
vocabularies, swap flow declarations, and ship — the platform
treats their bundle and the default identically.

The default bundle's full schema, structural rules, generation
order, and flow declarations live in
**`catapult-default-bundle-v3.md`** as reference content, with
worked YAML examples and per-flow sketches in
**`catapult-default-bundle-v3-examples.md`**. Both files attach
to this section as `reference`-edge targets from the default
bundle's component once the project is bootstrapped — they're
where downstream comparch and subcomparch passes pull schema
detail without dragging it into feature_expansion or sysarch.

A reader who wants to understand what Catapult *does* at the
"a Catapult project produces a feat → resp → comp → subcomp →
impl → plan → code chain" level reads only this section. A
reader who needs to author or modify the bundle reads the ref
docs.

---

# Part C — Architecture

v2 Part B carried over. Technologies, storage, HTTP, deployment,
real-world tooling choices. No content moves into or out of this
part in the v3 reorganization — it was already clearly scoped.

---

# Resolved framing decisions

- **Vocabulary for the two parts.** Part A is the **platform**;
  Part B is the **default bundle**. "Bundle" without qualifier
  refers to any bundle (the configuration system); "default
  bundle" is the specific one this spec describes in Part B.
- **Edge vocabulary split.** Platform owns the five edge **types**
  (`fanout`, `reference`, `dependency`, `policy_application`,
  `synthesis`); bundles declare named edge **instances** typed
  against one of those. `domain_parent` is a bundle-level
  instance typed as `synthesis`; the synthesis-tier minting and
  scheduling pattern is platform-level (platform mints and
  schedules aggregator instances), the specific `fanin` *kind*
  is bundle-level.
- **Code delivery / gitea.** Platform-level, tied to the
  `git_commit` generator type. Any tier declared with
  `generator: git_commit` inherits the substrate contract:
  one commit per tier instance, scope = declared territory,
  under the blocking-PR rule. Default bundle's `impl` tier
  picks `git_commit` and maps territory to folders (B.6).
- **Flow orchestration vs. flow content.** Platform owns walk
  mechanics, prompt sequencing, gating, scheduler composition.
  Bundles declare concrete flows (seed, optional phase-zero
  tier, direction, per-tier prompts). Two prompts per tier per
  flow: planning (produces a plan with `<implicated-children>`
  and optional `<structural-ops>`) and regeneration.
- **Phase-zero is its own tier per flow.** Bundle-declared
  singleton-per-flow-run tier with default context = platform's
  `expansion` and `sysarch` reads plus the flow's seed.
  Persists in event log; reviewed via normal lifecycle.
- **Plan gating.** Human-gate iff `<structural-ops>` is
  non-empty. Pure implicated-children plans auto-approve; users
  correct disagreements via deferred feedback.
- **Walk direction.** `down` or `up_then_down`. Upward leg is
  planning-only and advisory; the downward leg's plans drive
  scheduling. Split is always downward, always about children —
  no sibling-split prompt.
- **Five flows in the default bundle.** Feature-request,
  refactor, bug-fix-propagation, downward-propagation,
  upward-propagation. Scaffolding is *not* a flow — it's the
  scaffold's baseline behavior when no flow is active.
  Downward-propagation is mechanically just regen-with-feedback
  (the platform's reactive scheduler would do the cascade
  anyway), kept as an explicit flow declaration so bundles
  ship a worked example of consuming deferred feedback as a
  first-class operation.
- **Review UX invariants.** Plan review = effect set (editable
  visit/skip/trivial checklist); regen review = diff, not full
  doc.
- **Filesystem layout.** `scaffold/` carries the static DAG
  (tier and edge declarations); `flows/<flow>/` carries the
  flow's prompts (`plan.md`, `regen.md`, and `phase_zero.md`
  where applicable). Plan and regen prompts are **generic over
  tier**: tier-specific instructions (what does this tier do,
  what does its output mean) live on the tier declaration in
  `scaffold/`; flow prompts carry flow-specific framing (what's
  the purpose of this regen — fresh draft, propagation,
  refactor) and compose with the tier's instructions at runtime.
  Default bundle ships ~6 flow folders × ~3 files each instead
  of 9 tiers × 6 flows × 2 prompts = 108 files.

# Open questions for the v3 rewrite

1. **Generic-over-tier prompt composition.** The filesystem
   layout above assumes plan and regen prompts can be generic
   across tiers, with tier-specific framing pulled from the
   tier declarations in `scaffold/`. That's a real bet. v2's
   per-tier prompt files are highly tier-specific (the comparch
   prompt teaches API design; the subreqs prompt teaches
   responsibility decomposition). Worth verifying the split —
   tier teaches "what this tier means and what its draft
   grammar is for," flow teaches "what the regen's purpose
   is" — actually composes into a coherent LLM prompt before
   committing to the layout.
2. **Scope of B.11 (default bundle as YAML).** Deferred until
   the flow declaration shape is settled, since the YAML sketch
   needs to include flow declarations and we haven't pinned
   their grammar yet.
