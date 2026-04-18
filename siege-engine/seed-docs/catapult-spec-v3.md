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

The test for whether a topic belongs in A vs. B: if an L3 bundle
swapping the whole tier hierarchy would invalidate the paragraph,
it's bundle content and goes in B. If the paragraph stays true
regardless of which bundle is loaded, it's platform content and
goes in A.

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

### A.3.7 Levels of abstraction (L0–L3)
Full content from v2 §A.11.4, including the inheritance
promises table. Cross-referenced from A.1.3.

## A.4 Flows

Flows are **bundle-declared orchestrations** over the graph. The
platform owns the orchestration mechanics (walk, prompt
sequencing, gating, scheduler composition); bundles declare the
concrete flows — seed shape, optional phase-zero tier, direction,
per-tier prompts — alongside their tier and edge declarations.

### A.4.1 What a flow is
A flow declaration names:
- a **seed** (prose input, code diff, node-set-with-feedback, …),
- an optional **phase-zero tier** that shapes the seed into a
  structured starting artifact (see A.4.2),
- a **direction** (`down` or `up_then_down`),
- a **per-tier prompt pair**: planning + regeneration.

The platform runs the walk. At each visit, it runs the prompt pair
(or the direction-appropriate subset), honors readiness from the
reactive scheduler, and enqueues next-wave visits from the
approved plan's implicated-children list.

### A.4.2 Phase-zero as its own tier

Flows whose seed needs interpretation before the walk can start
declare a **phase-zero tier**: a bundle-declared singleton-per-
flow-run tier with its own scope, draft grammar, handle, and
prompt. Phase-zero artifacts persist in the event log, go through
the normal draft → review → approve lifecycle, and feed
downstream flow visits as plain context (the entry-tier planning
prompt reads `flow.phase_zero.handle` like any other context
edge).

Phase-zero's default context is the platform's `expansion` and
`sysarch` reads — "here's what this project already is, now
shape this input into work against it" — plus the flow's seed.
Bundles can extend with additional reads.

Filesystem-wise phase-zero lives in `flows/<flow>/phase_zero.md`
alongside the flow's plan and regen prompts.

### A.4.3 The two prompt pair per tier

**Planning prompt.** Input: upstream context (parent's plan for
downward flows; merged child plans for upward legs); the tier's
normal regen context; the flow's seed. Output: a parseable plan
artifact carrying two lists:

- `<implicated-children>` — structured entries per child with
  `disposition: visit | skip | trivial` and a one-line rationale.
  Platform consumes this list to enqueue the next wave. This is the
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

### A.4.4 Walk direction

**`down`** flows: plan → regen at every visit. Seed lands at the
declared entry tier; platform enqueues from each approved plan's
children list. Scaffolding, feature-request, refactor,
downward-propagation are all `down`.

**`up_then_down`** flows: upward leg runs **planning only**,
walking from seed(s) up to the tree root (multiple seeds
converge at common ancestors, where upward plans merge before
the next ancestor's planning). Upward-leg plans are
**advisory** — the platform does not enqueue from their
`<implicated-children>` lists. At root, the flow pivots: the
downward leg runs planning (fresh or reused from the seed-to-root
spine) + regeneration at every visited tier, and *downward-leg*
plans drive scheduling. Bug-fix propagation and
upward-propagation are `up_then_down`.

Split is always a downward-leg concern. There is no
sibling-split prompt type.

### A.4.5 Plan gating

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

### A.4.6 Review UX invariants

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

### A.4.7 Abstract flow catalogue

Stated bundle-agnostically; default-bundle instantiations in
B.10.

- **Scaffolding** — seed: raw input; direction: `down`;
  termination: leaf tier.
- **Feature request** — seed: feature-shaped prose; phase-zero
  shapes it into a feature list; direction: `down`; termination:
  leaf tier.
- **Refactor** — seed: structural-op prose; phase-zero surfaces
  the structural-ops list; direction: `down` with end-of-run
  structural-ops application.
- **Bug-fix propagation** — seed: code diff mapped to
  `git_commit`-owning leaves via territory (A.16); direction:
  `up_then_down`; no new code generated (input is already code).
- **Downward propagation** — seed: node-set-with-feedback;
  direction: `down`; scope-bounded propagation depth. The
  mechanically-thinnest flow in the catalogue: no phase-zero, no
  structural ops, just regen-with-feedback that the platform's
  reactive scheduler would do anyway. Kept as a flow declaration
  so bundles ship an explicit, editable example of how to consume
  deferred feedback as a first-class operation.
- **Upward propagation** — seed: node-set-with-feedback;
  direction: `up_then_down`.

### A.4.8 Flows and deferred feedback
Deferred feedback accumulates; flows consume. Refactoring of v2
§A.2.7, with the consumption list referencing the abstract flow
catalogue in A.4.7.

### A.4.9 Flow composition with the scheduler

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
- **Six flows in the default bundle.** Scaffolding,
  feature-request, refactor, bug-fix-propagation,
  downward-propagation, upward-propagation. Downward-propagation
  is mechanically just regen-with-feedback (the platform's
  reactive scheduler would do the cascade anyway), kept as an
  explicit flow declaration so bundles ship a worked example of
  consuming deferred feedback as a first-class operation.
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
