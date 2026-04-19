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

Five default-bundle flows, each declared per platform spec
§A.4 as a schema delta the platform grafts onto the scaffold
when the flow is active. Scaffolding is *not* in this list —
it's the scaffold's baseline behavior when no flow is active
(an approved input doc kicks the reactive scheduler; no
planning tiers, no delta).

Working sketches for each flow live in
`catapult-default-bundle-v3-examples.md`; this section carries
prose descriptions only.

### 10.1 Feature request
Seed: feature-shaped prose. Phase-zero planning tier splits
the request into one or more concrete features and lands them
at the expansion tier. Direction: `down` from the fan-out
point. Planning auto-approves. From v2 §A.2.2.

### 10.2 Refactor
Seed: structural-op prose. Phase-zero planning tier shapes the
request into a `<structural-ops>` list plus downstream plan.
Direction: `down`. Planning tiers' grammars allow
`<structural-ops>` → human-gated at any tier whose plan
carries structural-ops. Structural-ops applied end-of-run.
From v2 §A.2.3.

### 10.3 Bug-fix propagation
Seed: code diff mapped to `git_commit`-owning leaves via
territory (spec §A.16). Direction: `up_then_down`. Upward leg
produces planning-only assessments at each ancestor up to the
project root; merge-at-parent applies when multiple seed
leaves converge. Downward leg starts at root with plans and
regens, implicated-children splits fan out. No new code —
input is already code. From v2 §A.2.4.

### 10.4 Downward propagation
Seed: node-set-with-accumulated-feedback. Direction: `down`.
Scope-bounded propagation depth (v2 §A.2.5 retains the "stop
before impl" affordance via `max_depth`). Planning
auto-approves. The mechanically-thinnest flow in the
catalogue — kept as the worked example of consuming deferred
feedback as a first-class operation. From v2 §A.2.5.

### 10.5 Upward propagation
Seed: node-set-with-accumulated-feedback. Direction:
`up_then_down`. Same up-then-down shape as bug-fix propagation
but seeded from deferred feedback rather than a code diff.
From v2 §A.2.6.
