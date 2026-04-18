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
Six edge types: `fanout`, `reference`, `dependency`,
`domain_parent`, `policy_application`, `synthesis`. From v2
§A.11.6. Note to revisit whether `domain_parent` and
`policy_application` are properly engine-level or whether they
belong in Part B as default-system edge specializations —
current bet is engine-level (they're general patterns of
cross-kind subscription and cross-cutting application) but this
is the seam to interrogate carefully.

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

### A.4.1 What a flow is, abstractly
A flow is a **seed** (input or target set), an optional
**phase-0 expansion** that shapes the seed into concrete
tier-level work, a **graph walk** that produces a per-tier
**change plan** and per-tier regen at every tier the walk
touches, and an optional set of **structural operations**
applied at the end of the run. This is bundle-parametric: the
walk direction and the tiers touched are functions of the
bundle's schema, not hardcoded.

### A.4.2 The six flow shapes
Stated abstractly — direction, seed type, termination
condition. Tier-specific walks move to B.10.
- Scaffolding (seed: raw input; direction: downward along
  generation order; termination: leaf tier)
- Feature request (seed: feature-shaped prose; direction:
  downward from fan-out point; termination: leaf tier)
- Refactor (seed: structural-operation prose; direction:
  downward with end-of-run structural ops)
- Bug-fix propagation (seed: code diff; direction: upward with
  merge-at-parent, then downward siblings)
- Downward propagation (seed: accumulated feedback at a tier;
  direction: downward from that tier)
- Upward propagation (seed: accumulated feedback at a tier;
  direction: upward with merge-at-parent, optionally continuing
  downward)

### A.4.3 Change plans
Per-flow-run, per-tier reviewable intent artifacts. Not
structural DAG nodes; not projected into children. Persisted in
the event log as provenance. From v2 §A.4.3.

### A.4.4 Flows and deferred feedback
Deferred feedback accumulates; flows consume. Verbatim
refactoring of v2 §A.2.7, with the consumption list updated to
reference the abstract flow shapes.

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

## A.16 Code delivery substrate

v2 §A.10 (gitea, forge plugins, branch/PR model, one-commit-per-leaf,
PR granularity, blocking-PR rule). The substrate is engine-level
but its *shape* (one commit per leaf) is default-bundle and cross-
references B.4 / B.9.

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

## B.10 Flow walks on the default bundle

The tier-specific flow write-ups from v2 §A.2.1–§A.2.6, refiled
from Part A into here. Each walk now reads as "the
[scaffolding / feature request / …] flow shape (A.4.2)
instantiated on the default bundle's tier hierarchy."

### B.10.1 Scaffolding walk
v2 §A.2.1.
### B.10.2 Feature request walk
v2 §A.2.2.
### B.10.3 Refactor walk
v2 §A.2.3.
### B.10.4 Bug-fix propagation walk
v2 §A.2.4.
### B.10.5 Downward propagation walk
v2 §A.2.5.
### B.10.6 Upward propagation walk
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

# Open questions for the v3 rewrite

Things that fall out of the split and are worth deciding before
prose:

1. **Edge vocabulary split.** Is `domain_parent` genuinely
   engine-level (a general "cross-kind subscription" pattern) or
   is it specific enough to the default bundle's domain /
   presentational distinction to belong in B.2? Same question
   for `policy_application`. My current bet is engine-level for
   both, but the framing has to survive describing an L3 bundle
   that has neither.
2. **How long the engine flow descriptions can stay abstract.**
   The six flow shapes are recognizably the v2 flows with tier
   names elided, but some details (merge-at-parent in bug-fix
   propagation, phase-0 expansion shape) may not generalize off
   the default bundle cleanly. Worth trying to state abstractly
   and falling back to "the default bundle's instantiation is
   in B.10" where necessary.
3. **Whether code delivery (A.16) should be default-bundle
   content.** The gitea substrate is engine-level — every bundle
   needs *some* way to ship artifacts — but the "one commit per
   leaf, territory = folder" model is specific to the default
   bundle's `impl` tier having a folder-on-disk semantics. An
   L3 bundle for narrative writing wouldn't ship commits. The
   split probably wants the substrate in A.16 and the specific
   mapping in B.6 or a new B.12.
4. **Vocabulary for what we call the two parts.** "Engine" vs
   "default bundle" is clear but clunky; "core" vs "default
   system" or "platform" vs "bundle" are alternatives. Worth
   picking one before prose to keep the repeated framing snappy.
5. **Whether CLAUDE.md and v2-rearchitecture.md need the same
   reshuffling.** The CLAUDE.md phase-status summary implicitly
   uses the v2 vocabulary (feat/resp/comp/subcomp) because
   that's what's built. Not urgent — those docs describe the
   current implementation, which is the default bundle — but
   v3-style section cross-references from those docs will want
   to hit the new B.* numbering once the rewrite lands.
