# Catapult — Specification (v3 — TOC draft)

**Status:** organizational proposal, not yet prose. Each leaf section
carries a one- or two-line stub describing what lands there and
(where applicable) which v2 section the content is inherited or
refactored from.

The central structural bet of v3 is that **Part A describes the
engine** — what Catapult does regardless of bundle — and **Part B
describes the default bundle**, the graph-of-prompts design system
that ships with Catapult for AI code generation. Part C carries the
implementation architecture (v2 Part B, moved and otherwise
unchanged).

The test for whether a topic belongs in A vs. B: if an L3 bundle
swapping the whole tier hierarchy would invalidate the paragraph,
it's default-system content and goes in B. If the paragraph stays
true regardless of which bundle is loaded, it's engine content and
goes in A.

---

# Part A — Engine

## A.0 Vision

Inherited verbatim from v2 §Vision. The vision is bundle-agnostic
and doesn't need to be restated per bundle.

## A.1 What Catapult is

### A.1.1 Design memory, not a code generator or documentation tool
Lifted from v2 §Vision opening — the core framing about holding
design intent. Reframed to make explicit that the design graph's
*shape* is a bundle concern; only the commitment to hold the
graph is engine-level.

### A.1.2 The two engine commitments
One subsection stating both load-bearing invariants together:
the model is an **event-sourced projection** (every write an
event, state derived by reducer), and the scheduler is a
**reactive runtime** over a typed graph declared in a bundle.
These are the two sentences that define Catapult; everything
else in Part A derives from them.

### A.1.3 Engine invariants vs. default-system invariants
Promote the L0–L3 inheritance table from v2 §A.11.4 to this top
slot and use it as the organizing principle for the whole
document. Rows that hold at every level belong in Part A; rows
that go bundle-owned at L3 belong in Part B.

## A.2 The structured model

### A.2.1 Events, reducer, projections
Refactor of v2 §A.1.1. Drops the tier-specific examples and
states the reducer/projection invariants abstractly.

### A.2.2 IDs as opaque lineage markers
Refactor of v2 §A.1.4. Keep the `<kind>_<8 char>` shape as an
engine-level convention; drop the `feat_*`/`comp_*` examples in
favor of `<tier>_*` placeholders. Default-bundle tier names go
to B.

### A.2.3 Instructions as the only write path
Pulled from scattered v2 mentions (§A.1.1, §A.1.3 tail). States
the rule engine-abstractly: every write is either a draft
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

Five engine-level edge **types**, each with its own cardinality,
graph-constraint, and readiness semantics: `fanout`, `reference`,
`dependency`, `policy_application`, `synthesis`. The engine
declares the type vocabulary; bundles declare **named edge
instances** typed against one of these types, with particular
source and target tiers. From v2 §A.11.6.

- `fanout` — parent-creates-children; how every tier decomposes.
- `reference` — general-purpose advisory-context edge; acyclic.
- `dependency` — data dependency with `graph_constraint: acyclic`
  support; stays engine-level because the constraint machinery is
  engine-owned.
- `policy_application` — cross-cutting application of a policy
  node to a target, with reachability. Engine-level; the general
  "some nodes carry obligations that apply elsewhere" pattern is
  bundle-agnostic.
- `synthesis` — reverse aggregation. Engine declares the pattern
  (a child-aggregating tier subscribed-to via named edges);
  bundles declare which tier does the aggregating and which tier
  subscribes. The default bundle's `fanin` tier and its
  `domain_parent` edge are named instantiations in B.1.8 and
  B.2.2 — the engine mints `fanin` instances, manages the
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

### A.3.7 Levels of abstraction (L0–L3)
Full content from v2 §A.11.4, including the inheritance
promises table. Cross-referenced from A.1.3.

## A.4 Flows

Flows are **bundle-declared orchestrations** over the graph.
Engine owns the orchestration mechanics (walk, prompt sequencing,
gating, scheduler composition); bundles declare the concrete
flows — seed shape, direction, per-tier prompts — alongside their
tier and edge declarations.

### A.4.1 What a flow is
A flow declaration names:
- a **seed** (prose input, code diff, node-set-with-feedback, …),
- an optional **phase-zero** step (LLM call that shapes the seed
  into a structured artifact at an entry tier),
- a **direction** (`down` or `up_then_down`),
- a **per-tier prompt pair**: planning + regeneration.

The engine runs the walk. At each visit, it runs the prompt pair
(or the direction-appropriate subset), honors readiness from the
reactive scheduler, and enqueues next-wave visits from the
approved plan's implicated-children list.

### A.4.2 The two prompt pair per tier

**Planning prompt.** Input: upstream context (parent's plan for
downward flows; merged child plans for upward legs); the tier's
normal regen context; the flow's seed. Output: a parseable plan
artifact carrying two lists:

- `<implicated-children>` — structured entries per child with
  `disposition: visit | skip | trivial` and a one-line rationale.
  Engine consumes this list to enqueue the next wave. This is the
  reviewer's effect checklist.
- `<structural-ops>` — optional. Proposed renames, reparents,
  promotes, demotes, merges, splits, deletes. Queued for
  end-of-run application per v2 §A.2.3.

The plan artifact is the unified change-plan and split-decision
node — v2's separate `changeplan_*` tier and a would-be
"split output" collapse into one. One approval captures intent
and child-routing together.

**Regeneration prompt.** Input: the approved plan plus the
tier's normal regen context. Output: a draft of the tier's
content, parsed through the tier's existing `draft.grammar`.
The draft review is diff-based against prior approved content,
never a whole-doc re-read.

### A.4.3 Walk direction

**`down`** flows: plan → regen at every visit. Seed lands at the
declared entry tier; engine enqueues from each approved plan's
children list. Scaffolding, feature-request, refactor,
downward-propagation are all `down`.

**`up_then_down`** flows: upward leg runs **planning only**,
walking from seed(s) up to the tree root (multiple seeds
converge at common ancestors, where upward plans merge before
the next ancestor's planning). Upward-leg plans are
**advisory** — the engine does not enqueue from their
`<implicated-children>` lists. At root, the flow pivots: the
downward leg runs planning (fresh or reused from the seed-to-root
spine) + regeneration at every visited tier, and *downward-leg*
plans drive scheduling. Bug-fix propagation and
upward-propagation are `up_then_down`.

Split is always a downward-leg concern. There is no
sibling-split prompt type.

### A.4.4 Plan gating

Plan approval follows the "approval gates only destructive
operations" rule from A.8.2 / v2 §A.3.3:

- Plan carries non-empty `<structural-ops>` → **human-gated**.
  Refactor flows and any flow that proposes a rename / reparent /
  promote / demote / merge / split / delete hit this path.
- Plan carries only `<implicated-children>` → **auto-approved**.
  The child-visit list is non-destructive (every visited child
  produces a reviewable diff; every skipped child preserves
  existing state). Scaffolding, feature-request, and propagation
  flows typically auto-approve every plan they produce.

Users correct auto-approved plans they later disagree with via
the normal deferred-feedback loop — leave feedback on the
affected node, kick a propagation flow.

Bundles can opt any individual flow into stricter gating
(`planning.gate: always`) for workflows that want hand-review
of every tier's intent.

### A.4.5 Review UX invariants

These constrain how any bundle-declared flow presents approvals,
so the review experience is consistent across flows and across
bundles:

- **Plan review surfaces the effect set, not the prompt output.**
  The reviewer sees the structured `<implicated-children>` list
  as a visit/skip/trivial checklist with rationales, editable
  before approval. The raw plan text is for AI and debugging,
  collapsed behind a "show reasoning" toggle.
- **Regen review is a diff.** Every regen (flow-driven or
  standalone) presents its review as a diff against the prior
  approved content, never a full-document re-read. Per-fragment
  diffing falls out naturally from the fragment model.

### A.4.6 Abstract flow catalogue

Stated bundle-agnostically; default-bundle instantiations in
B.10.

- **Scaffolding** — seed: raw input; direction: `down`;
  termination: leaf tier.
- **Feature request** — seed: feature-shaped prose; phase-zero
  lands at the extraction tier; direction: `down`; termination:
  leaf tier.
- **Refactor** — seed: structural-op prose; phase-zero surfaces
  the structural-ops list; direction: `down` with end-of-run
  structural-ops application.
- **Bug-fix propagation** — seed: code diff mapped to
  `git_commit`-owning leaves via territory (A.16); direction:
  `up_then_down`; no new code generated (input is already code).
- **Downward propagation** — seed: node-set-with-feedback;
  direction: `down`; scope-bounded propagation depth.
- **Upward propagation** — seed: node-set-with-feedback;
  direction: `up_then_down`.

### A.4.7 Flows and deferred feedback
Deferred feedback accumulates; flows consume. Refactoring of v2
§A.2.7, with the consumption list referencing the abstract flow
catalogue in A.4.6.

### A.4.8 Flow composition with the scheduler

Flows don't bypass readiness — a flow visit still waits for its
tier's `context:` to resolve. Framing: an active flow restricts
*which* `(tier, scope)` pairs the scheduler considers for its
next enqueue, rather than enqueueing directly. Idle-mode
scheduler fires everything ready; flow-mode scheduler fires
only visits the flow has queued, still gated on context
readiness. The lobby's one-flow-per-project rule (A.9.1) makes
the composition unambiguous.

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
traversal rules are engine-level.

### A.6.2 Permission atoms and roles
v2 §A.14.1, §A.14.3.

### A.6.3 Review routing and SLA
v2 §A.5.4 tail.

## A.7 Projection sources

### A.7.1 Bootstrap nodes
Authored prose that mints structured children on approval.
From v2 §A.4.1, §A.4.2. Engine-level mechanism; which tiers are
bootstraps is a bundle decision.

### A.7.2 Mint determinism from approved content
Parsing → event emission → reducer projection must be
deterministic. From v2 §A.4.

## A.8 Structural operations

### A.8.1 Instruction vocabulary
Rename, reparent, promote, demote, merge, split, per-edge-type
create/delete. From v2 §A.1.3 tail and §A.4.
Bundle-parametric — an L2 bundle with new tiers inherits the
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
model, PR granularity, blocking-PR rule) is engine-level; any
tier whose bundle declaration picks `generator: git_commit`
inherits it.

### A.16.1 The `git_commit` generator contract
On approval of a tier instance using this generator, the engine
produces a commit whose scope is the instance's declared
territory (a `{repository, folder}` tuple, addressable by the
tier's fields), on the branch the active flow run owns, under
the blocking-PR rule. One commit per instance of any tier using
`git_commit`. Territory becomes engine-level because the
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
v2 §A.10.4, §A.10.5, §A.10.6 — all engine-level, part of the
`git_commit` contract.

### A.16.5 Git is only for code, not for design
v2 §A.10.7.

## A.17 Admin and governance

v2 §A.21, §A.22.

## A.18 AI sandboxing

v2 §A.18.

---

# Part B — The default bundle

## B.0 Overview

### B.0.1 What the default bundle is for
Graph-of-prompts design system for AI code generation. Takes a
prose input document and produces a layered structured model —
features, responsibilities, components, subcomponents,
implementations, plans, code — through a reviewable pipeline.

### B.0.2 Bundle summary at a glance
One-page cheat sheet: the tier list, the edge list, the fragment
kinds, the cold-start order, the meaning-engine framing. Gives
a reader who only needs the default-bundle story something to
anchor on before the rest of B unfolds.

## B.1 Tier vocabulary

One subsection per tier. Each is a refactoring of the
corresponding v2 §A.1.2 bullet into a proper section with its
scope, identity, handle, draft grammar reference, and generator.

### B.1.1 `feat` — features
### B.1.2 `resp` — responsibilities (tier-agnostic IDs; top-level vs subresp lives in parent)
### B.1.3 `comp` — components (tier-agnostic IDs; domain vs presentational kind)
### B.1.4 `subcomp` — subcomponents (same kind as `comp`; structural tier only)
### B.1.5 `impl` — implementation leaves
### B.1.6 `plan` — per-impl plan nodes
### B.1.7 `policy` — cross-cutting constraints (§B.5)
### B.1.8 `fanin` — domain fan-in synthesis (§B.4.4)
### B.1.9 `ref` — project reference documents (§B.8)
### B.1.10 `vocab` — project vocabulary terms (§B.7)
### B.1.11 Bootstrap tiers
`expansion`, `reqs`, `sysarch`, `subreqs`, `manifest`. One
subsubsection each, explaining which children each bootstrap
mints. From v2 §A.1.2.
### B.1.12 `changeplan` — per-flow-run intent nodes
Per v2 §A.4.3; explicitly not a structural DAG node.

## B.2 Edge vocabulary

### B.2.1 `dependency`
v2 §A.1.3.
### B.2.2 `domain_parent`
v2 §A.1.3, §A.1.8.
### B.2.3 `policy_application`
v2 §A.1.3, §A.1.10.
### B.2.4 `decomposition`
Both conventions (`feat→resp`, top-resp→subresp). v2 §A.1.3.
### B.2.5 `reference`
v2 §A.1.3, §A.1.13.

## B.3 Fragments and transclusion

### B.3.1 Section vocabulary and order
`techspec`, `pubapi`, `privapi`, `policies`, `deps`. v2 §A.1.5.
### B.3.2 Fragment-level diff as drift signal
v2 §A.1.5 tail.

## B.4 Structural rules

### B.4.1 Foundation components
v2 §A.1.6.
### B.4.2 Subcomponent depth cap
v2 §A.1.7.
### B.4.3 Unified domain/presentational DAG
v2 §A.1.8.
### B.4.4 Domain fan-in synthesis
v2 §A.1.9.

## B.5 Policies

v2 §A.1.10 in full. Shape, two-tier generation, application at
component-architecture time, policy-induced dep edges.

## B.6 Ownership and repository territory

v2 §A.1.11. The territory model is default-bundle-specific
(it's a property of the `impl` tier having `{repository,
folder}` fields); ownership-as-scoped-role is engine-level and
lives in A.6.

## B.7 Project vocabulary

v2 §A.1.12 in full.

## B.8 Project references

v2 §A.1.13 in full.

## B.9 Generation plan

### B.9.1 Cold-start order
v2 §A.3.1.
### B.9.2 The default bundle as a meaning engine
Compression / rotation / expansion / articulation framing. v2
§A.3.1a.
### B.9.3 Context assembly strategy
v2 §A.3.5.

## B.10 Flow declarations on the default bundle

The six default-bundle flows, each declared per A.4.1 with
seed shape, optional phase-zero, direction, and the per-tier
(planning, regeneration) prompt pair. Tier-specific prompt
content is the bundle author's work; the shapes below describe
which tiers each flow touches.

### B.10.1 Scaffolding
Seed: raw input document. Phase-zero: none (input expansion is
the first bootstrap). Direction: `down`. Tiers touched:
expansion → reqs → sysarch → subreqs → comparch → subcomparch →
impl → plan → code. Planning auto-approves at every tier (no
structural ops). From v2 §A.2.1.

### B.10.2 Feature request
Seed: feature-shaped prose. Phase-zero: LLM call that splits the
request into one or more concrete features and lands them at the
expansion tier. Direction: `down` from the fan-out point.
Planning auto-approves. From v2 §A.2.2.

### B.10.3 Refactor
Seed: structural-op prose. Phase-zero: LLM call that shapes the
request into a `<structural-ops>` list plus downstream plan.
Direction: `down`. **Planning human-gates at every tier whose
plan carries structural-ops** — which is most of them for a
refactor — matching the destructive-op approval rule.
Structural-ops applied end-of-run. From v2 §A.2.3.

### B.10.4 Bug-fix propagation
Seed: code diff mapped to `git_commit`-owning leaves via
territory (A.16). Direction: `up_then_down`. Upward leg
produces planning-only diagnoses at each ancestor up to the
project root; merge-at-parent applies when multiple seed leaves
converge. Downward leg starts at root with regeneration and
implicated-children splits. No new code — input is already
code. From v2 §A.2.4.

### B.10.5 Downward propagation
Seed: node-set-with-accumulated-feedback. Direction: `down`.
Scope-bounded propagation depth (v2 §A.2.5 retains the "stop
before impl" affordance). Planning auto-approves. From v2
§A.2.5.

### B.10.6 Upward propagation
Seed: node-set-with-accumulated-feedback. Direction:
`up_then_down`. Same up-then-down shape as bug-fix propagation
but seeded from deferred feedback rather than a code diff. From
v2 §A.2.6.

## B.11 Default bundle as YAML

The ~220-line YAML sketch from v2 §A.11.6 (What this produces).
Lives here rather than in A.11 because it's the serialization of
this specific bundle, not of the bundle system.

---

# Part C — Architecture

v2 Part B carried over. Technologies, storage, HTTP, deployment,
real-world tooling choices. No content moves into or out of this
part in the v3 reorganization — it was already clearly scoped.

---

# Resolved framing decisions

- **Edge vocabulary split.** Engine owns the five edge **types**
  (`fanout`, `reference`, `dependency`, `policy_application`,
  `synthesis`); bundles declare named edge **instances** typed
  against one of those. `domain_parent` is a bundle-level
  instance typed as `synthesis`; the `fanin` tier pattern is
  engine-level (engine mints and schedules synthesis-tier
  aggregators), the specific `fanin` *kind* is bundle-level.
- **Code delivery / gitea.** Engine-level, tied to the
  `git_commit` generator type. Any tier declared with
  `generator: git_commit` inherits the substrate contract:
  one commit per tier instance, scope = declared territory,
  under the blocking-PR rule. Default bundle's `impl` tier
  picks `git_commit` and maps territory to folders (B.6).
- **Flow orchestration vs. flow content.** Engine owns walk
  mechanics, prompt sequencing, gating, scheduler composition.
  Bundles declare concrete flows (seed, phase-zero, direction,
  per-tier prompts). Two prompts per tier per flow: planning
  (produces a plan with `<implicated-children>` and optional
  `<structural-ops>`) and regeneration.
- **Plan gating.** Human-gate iff `<structural-ops>` is
  non-empty. Pure implicated-children plans auto-approve; users
  correct disagreements via deferred feedback.
- **Walk direction.** `down` or `up_then_down`. Upward leg is
  planning-only and advisory; the downward leg's plans drive
  scheduling. Split is always downward, always about children —
  no sibling-split prompt.
- **Review UX invariants.** Plan review = effect set (editable
  visit/skip/trivial checklist); regen review = diff, not full
  doc.

# Open questions for the v3 rewrite

1. **Vocabulary for the two parts.** "Engine" vs "default
   bundle" is clear but clunky; "core" vs "default system" or
   "platform" vs "bundle" are alternatives. Worth picking one
   before prose to keep the repeated framing snappy.
2. **Scope of B.11 (default bundle as YAML).** How complete a
   YAML sketch to ship — the ~220-line form from v2 §A.11.6
   covered tiers and edges but not flow declarations. Flow YAML
   shape needs to be sketched; ideally it's small enough that
   B.11 shows the whole default bundle including all six flows
   on one scrollable page.
3. **Phase-zero prompt as a separate prompt type.** Flow
   declarations name an optional `phase_zero` step. Is phase-zero
   a third prompt type alongside planning and regeneration, or
   a special-cased instance of planning ("plan at the entry
   tier, seed-shape-dependent")? Leaning toward "third prompt
   type, rare, runs once per flow" — planning at the entry tier
   already has upstream-plan context that phase-zero doesn't.
4. **Prompt-bundle naming / filesystem layout.** With flows
   multiplying per-tier prompt count (from 1–2 prompts per tier
   to 2–3 per tier per flow), the bundle's prompt directory
   layout needs a clear convention. `prompts/<tier>/<flow>/plan.md`
   and `prompts/<tier>/<flow>/regen.md` is the obvious shape but
   worth checking it doesn't explode with 9 tiers × 6 flows = 54
   directories for the default bundle.
