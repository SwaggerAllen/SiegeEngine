# Catapult — Default bundle reference

**Status:** TOC draft, not yet prose. Each leaf section carries
a one- or two-line stub describing what lands there and which
v2 section the content is inherited or refactored from.

This is the **default bundle reference**. The platform spec
(`catapult-spec-v3.md`) describes the bundle at the level needed
to mint it as a feature; this file holds the schema, structural
rules, and generation plan in detail. Bundle authors and
implementers read this; feature_expansion / sysarch don't —
they read the spec and pull this in via a `reference` edge from
the default-bundle feature node.

YAML examples for the bundle's tier, edge, fragment, and flow
declarations live in the companion file
`catapult-default-bundle-v3-examples.md`.

---

## Overview

### What the default bundle is for
Graph-of-prompts design system for AI code generation. Takes a
prose input document and produces a layered structured model —
features, responsibilities, components, subcomponents,
implementations, plans, code — through a reviewable pipeline.

### Bundle summary at a glance
One-page cheat sheet: the tier list, the edge list, the fragment
kinds, the cold-start order, the meaning-engine framing. Gives
a reader who only needs the default-bundle story something to
anchor on before the rest unfolds.

## 1. Tier vocabulary

One subsection per tier. Each is a refactoring of the
corresponding v2 §A.1.2 bullet into a proper section with its
scope, identity, handle, draft grammar reference, and generator.

### 1.1 `feat` — features
### 1.2 `resp` — responsibilities (tier-agnostic IDs; top-level vs subresp lives in parent)
### 1.3 `comp` — components (tier-agnostic IDs; domain vs presentational kind)
### 1.4 `subcomp` — subcomponents (same kind as `comp`; structural tier only)
### 1.5 `impl` — implementation leaves
### 1.6 `plan` — per-impl plan nodes
### 1.7 `policy` — cross-cutting constraints (§5)
### 1.8 `fanin` — domain fan-in synthesis (§4.4)
### 1.9 `ref` — project reference documents (§8)
### 1.10 `vocab` — project vocabulary terms (§7)
### 1.11 Bootstrap tiers
`expansion`, `reqs`, `sysarch`, `subreqs`, `manifest`. One
subsubsection each, explaining which children each bootstrap
mints. From v2 §A.1.2.
### 1.12 `changeplan` — per-flow-run intent nodes
Per v2 §A.4.3; explicitly not a structural DAG node.

## 2. Edge vocabulary

Named edge instances, each typed against one of the platform's
five edge types (see platform spec §A.3.2).

### 2.1 `dependency`
v2 §A.1.3.
### 2.2 `domain_parent`
Bundle-level edge typed as `synthesis` — presentational comp
subscribes to domain comp's `fanin` aggregator. v2 §A.1.3,
§A.1.8.
### 2.3 `policy_application`
v2 §A.1.3, §A.1.10.
### 2.4 `decomposition`
Both conventions (`feat→resp`, top-resp→subresp). v2 §A.1.3.
### 2.5 `reference`
v2 §A.1.3, §A.1.13.

## 3. Fragments and transclusion

### 3.1 Section vocabulary and order
`techspec`, `pubapi`, `privapi`, `policies`, `deps`. v2 §A.1.5.
### 3.2 Fragment-level diff as drift signal
v2 §A.1.5 tail.

## 4. Structural rules

### 4.1 Foundation components
v2 §A.1.6.
### 4.2 Subcomponent depth cap
v2 §A.1.7.
### 4.3 Unified domain/presentational DAG
v2 §A.1.8.
### 4.4 Domain fan-in synthesis
v2 §A.1.9.

## 5. Policies

v2 §A.1.10 in full. Shape, two-tier generation, application at
component-architecture time, policy-induced dep edges.

## 6. Ownership and repository territory

v2 §A.1.11. The territory model is bundle-specific (a property
of the `impl` tier having `{repository, folder}` fields);
ownership-as-scoped-role is platform-level and lives in spec
§A.6.

## 7. Project vocabulary

v2 §A.1.12 in full.

## 8. Project references

v2 §A.1.13 in full.

## 9. Generation plan

### 9.1 Cold-start order
v2 §A.3.1.
### 9.2 The default bundle as a meaning engine
Compression / rotation / expansion / articulation framing. v2
§A.3.1a.
### 9.3 Context assembly strategy
v2 §A.3.5.

## 10. Flow declarations on the default bundle

Five default-bundle flows, each a **schema delta** per platform
spec §A.4: the bundle declares planning tiers, edges, phase-zero
tiers (where applicable), and prompt files; the platform merges
them onto the scaffold when the flow is active. Each flow also
declares an `invokes:` hook naming the walk algorithm that drives
traversal — one of two platform primitives, `downward_cascade` or
`up_then_down`. Scaffolding is *not* in this list — it's the
scaffold's baseline behavior when no flow is active (an approved
input doc kicks the reactive scheduler; no delta, no primitive
invocation).

Working sketches for each flow live in
`catapult-default-bundle-v3-examples.md`; this section carries
prose descriptions only.

### 10.1 Feature request
Seed: feature-shaped prose. Phase-zero planning tier splits the
request into one or more concrete features, expressed as
`<additions>` in the expansion-tier plan. Invokes
`downward_cascade`; walk fans out through reqs → sysarch →
subreqs → comparch → subcomparch → impl → plan → code integrating
the new features. Planning auto-approves. From v2 §A.2.2.

### 10.2 Refactor
Seed: structural-op prose. Phase-zero planning tier shapes the
request into a `<structural-ops>` list plus downstream intent.
Invokes `downward_cascade`. Planning tier grammars allow
`<structural-ops>` → plans carrying ops are human-gated per the
`gate: non-empty-structural-ops` annotation. **Ops apply
immediately on plan approval**; each tier's regen sees the
post-op state as current. No deferred application, no
ready-to-apply state. From v2 §A.2.3 (modified —
immediate-apply replaces the v2 end-of-run deferral).

### 10.3 Bug-fix propagation
Seed: code diff. A phase-zero tier maps the diff's changed paths
to owning `impl_*` leaves via `scaffold.manifest.resolve_paths`
(spec §A.16 / territory) and emits an `<affected-leaves>` set.
Invokes `up_then_down`. Upward leg produces planning-only
`<assessment>` at each ancestor up to the project root;
merge-at-parent is implicit via the upward planning tiers'
cardinality-many `child_plans` context. Downward leg starts at
root with plans and regens, implicated-children splits fan out.
No new code generated — input is already code. From v2 §A.2.4.

### 10.4 Downward propagation
Seed: node-set-with-accumulated-feedback. Invokes
`downward_cascade` with default prompts; no phase-zero, no
structural ops, no additions. Scope-bounded via a `max_depth`
parameter (v2 §A.2.5's "stop before impl" affordance). Planning
auto-approves. The mechanically-thinnest flow in the catalogue —
kept as the reference implementation of feedback consumption.
From v2 §A.2.5.

### 10.5 Upward propagation
Seed: node-set-with-accumulated-feedback. Invokes `up_then_down`
with default prompts; no phase-zero. Upward leg produces
`<assessment>` at each ancestor; downward leg cascades the
revisions back through the seed-to-root spine plus sideways
fan-outs. Reference implementation of the up-then-down pattern
that bug-fix uses with a different seed shape. From v2 §A.2.6.
