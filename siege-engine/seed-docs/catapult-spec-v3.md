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

Inherited verbatim from v2 §Vision. The vision is bundle-agnostic
and doesn't need to be restated per bundle.

## A.1 What Catapult is

### A.1.1 Design memory, not a code generator or documentation tool
Lifted from v2 §Vision opening — the core framing about holding
design intent. Reframed to make explicit that the design graph's
*shape* is a bundle concern; only the commitment to hold the
graph is platform-level.

### A.1.2 The two platform commitments
One subsection stating both load-bearing invariants together:
the model is an **event-sourced projection** (every write an
event, state derived by reducer), and the scheduler is a
**reactive runtime** over a typed graph declared in a bundle.
These are the two sentences that define Catapult; everything
else in Part A derives from them.

### A.1.3 Platform invariants vs. bundle invariants
The organizing principle for the rest of the spec. Platform
invariants are properties of the event-sourced reducer and the
reactive-schema runtime (A.1.2) — true for every Catapult
project regardless of bundle. Bundle invariants are properties
of a specific schema (tier vocabulary, edge instances, flow
declarations, structural rules) — true when that bundle is
loaded. The invariants the platform ships with, stated
concretely: append-only event log, reducer-materialized
projections, instructions-as-the-only-write-path (A.2),
typed-schema scheduling (A.3), one-flow-per-project lobby
(A.9.1), review/feedback/regen lifecycle (A.5), change-plan
provenance (A.4.3).

## A.2 The structured model

### A.2.1 Events, reducer, projections
Refactor of v2 §A.1.1. Drops the tier-specific examples and
states the reducer/projection invariants abstractly.

### A.2.2 IDs as opaque lineage markers
Refactor of v2 §A.1.4. Keep the `<kind>_<8 char>` shape as an
platform-level convention; drop the `feat_*`/`comp_*` examples in
favor of `<tier>_*` placeholders. Default-bundle tier names go
to B.

### A.2.3 Instructions as the only write path
Pulled from scattered v2 mentions (§A.1.1, §A.1.3 tail). States
the rule platform-abstractly: every write is either a draft
approval or a structured instruction; nothing mutates rows
directly.

## A.3 The bundle as reactive schema

The load-bearing chapter of v3. Everything here is currently in
v2 §A.11.6 and needs to be promoted so it arrives before the
reader has internalized the default bundle's vocabulary.

### A.3.1 Tiers
`scope` / `scope_filter` / `permitted_parents` / `identity` /
`fields` / `handle` / `draft` / `generator` / `context` /
`produces`. From v2 §A.11.6.

### A.3.2 Edges

Five platform-level edge **types**, each with its own cardinality,
graph-constraint, and readiness semantics: `fanout`, `reference`,
`dependency`, `policy_application`, `synthesis`. The platform
declares the type vocabulary; bundles declare **named edge
instances** typed against one of these types, with particular
source and target tiers. From v2 §A.11.6.

- `fanout` — parent-creates-children; how every tier decomposes.
- `reference` — general-purpose advisory-context edge; acyclic.
- `dependency` — data dependency with `graph_constraint: acyclic`
  support; stays platform-level because the constraint machinery is
  platform-owned.
- `policy_application` — cross-cutting application of a policy
  node to a target, with reachability. Platform-level; the general
  "some nodes carry obligations that apply elsewhere" pattern is
  bundle-agnostic.
- `synthesis` — reverse aggregation. Platform declares the pattern
  (a child-aggregating tier subscribed-to via named edges);
  bundles declare which tier does the aggregating and which tier
  subscribes. The default bundle's `fanin` tier and its
  `domain_parent` edge are named instantiations in B.1.8 and
  B.2.2 — the platform mints `fanin` instances, manages the
  first-pass readiness gate and staling on subcomponent change,
  and exposes the aggregated handle; the bundle says *which*
  presentational tier subscribes via `domain_parent`.

### A.3.3 Fragments as authored-only content
From v2 §A.11.6 — the "no projected-fragment category" point.
Keep the `produces:` mechanism.

### A.3.4 Context walks
From v2 §A.11.6. Context is the only readiness signal; all
gating (fan-in first-pass, presentational-waits-for-fanin,
etc.) falls out of context resolution.

### A.3.5 Predicate language
Six operator families, the four slots predicates appear in, the
named-predicate escape hatch. From v2 §A.11.6.

### A.3.6 Scheduler as reactive runtime
Enumerate / evaluate / enqueue; staling as the reactive dual.
Merges v2 §A.3.2 and §A.11.6. The state-driven scheduler and
the reactive-schema scheduler are the same machine; v2 described
them in two places because the reactive framing was late.

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

All sub-sections here are bundle-parametric. From v2 §A.5
wholesale, with tier-specific examples replaced by
`<bootstrap_tier>` / `<arch_tier>` placeholders.

### A.5.1 Draft → AI self-review → human review → approve
v2 §A.5.1.

### A.5.2 AI self-review
v2 §A.5 (AI self-review subsection) + CLAUDE.md summary.

### A.5.3 Deferred feedback
v2 §A.5.2.

### A.5.4 Collaborative discussions
v2 §A.5.3.

### A.5.5 Status chains
v2 §A.5.5.

### A.5.6 Review granularity and batching
v2 §A.5.6.

### A.5.7 Restart semantics
v2 §A.5.7.

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
