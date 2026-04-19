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

The default bundle is Catapult's **graph-of-prompts design
system for AI code generation**. It takes a prose input
document describing a project and produces a layered
structured model — features, responsibilities, components,
subcomponents, implementations, plans, code — through a
reviewable pipeline that terminates in commits on a code
repository.

The bundle's shape is an opinionated answer to "how should
AI generate code well?" The answer this bundle commits to:
stage the design thinking in tiers before any code is
produced, review each tier's output, and let downstream
generation consume the approved upstream handles rather
than trying to reason about the whole project in one
prompt. Small well-scoped prompts produce better output
than one massive prompt.

Most Catapult users will encounter this bundle and think of
it as "Catapult." The platform's generality (A.3) matters
because the bundle's design commitments are choices, not
laws — a different bundle could decompose differently — but
the default bundle is what ships with Catapult and what
most documentation references.

### Bundle summary at a glance

**Node tiers (12):** `feat`, `resp`, `comp`, `subcomp`,
`impl`, `plan`, `policy`, `fanin`, `ref`, `vocab`,
`changeplan`, plus the five bootstrap tiers `expansion`,
`reqs`, `sysarch`, `subreqs`, `manifest`.

**Edge instances (5):** `dependency`, `domain_parent`,
`policy_application`, `decomposition`, `reference`.

**Fragment kinds (5):** `techspec`, `pubapi`, `privapi`,
`policies`, `deps`.

**Structural rules:** foundation component at every
structural level, two-level component depth cap, unified
domain/presentational DAG with fan-in synthesis for
fanned-out domain components.

**Cold-start order:** input → expansion → reqs → sysarch →
subreqs → comparch → subcomparch → impl → plan → code.

**Flows (5):** feature-request, refactor, bug-fix
propagation, downward propagation, upward propagation.
Scaffolding is the scaffold's baseline behavior, not a
flow.

## 1. Tier vocabulary

One subsection per tier. Each pins the tier's scope,
identity, handle, draft grammar (where applicable), and
generator.

### 1.1 `feat` — features

The unit a user thinks in ("billing," "collaborative
editing"). Features are **slices, not containers** — a
single feature can implicate many components, and a single
component can serve many features. The feature tier is
where the LLM commits to the vocabulary a downstream
reader uses to talk about the project's capabilities.

- **Scope:** minted as children of `expansion`; multiple
  per project.
- **Identity:** `id` for downstream reference; `name` for
  human intent.
- **Handle:** `name`, one-paragraph summary, outgoing
  `decomposition` edges to the responsibilities it
  implicates.
- **Draft:** none — feat is a join target minted by
  expansion's fanout (see §1.11).
- **Generator:** none; handle is composed from the
  approved expansion content plus projected decomposition
  edges.

### 1.2 `resp` — responsibilities

Features decompose into responsibilities — the
system-level obligations that collectively fulfill a
feature's user-facing intent. The `resp` tier is
**tier-agnostic for ID purposes**: top-level
responsibilities (minted by `reqs`) and per-component
subresponsibilities (minted by each component's
`subreqs`) both use the `resp_` prefix. The distinction
between top-level and subresp lives in the parent
assignment, not the kind — so promotion or demotion
between the tiers preserves the ID.

- **Scope:** minted as children of either `reqs`
  (top-level) or `subreqs` (per-component subresp).
- **Identity:** `id`.
- **Handle:** `name`, prose summary, incoming decomposition
  edges (from the parent or from `feat` for top-level).
- **Draft:** none — join target.
- **Generator:** none.

### 1.3 `comp` — components

A component. Every top-level responsibility maps to
exactly one **domain** component (many-to-one). A
responsibility may additionally appear in one
presentational component if that presentational component
has a `domain_parent` edge to the domain component that
owns the responsibility. The presentational assignment is
a mirror, not an independent ownership.

The `comp` tier is also **tier-agnostic for ID purposes**
— top-level components and subcomponents both use the
`comp_` prefix. Structural tree is hard-capped at two
component levels (see §4.2).

- **Scope:** minted as children of `sysarch` (top-level)
  or `subcomp` declarations (subcomponent; see §1.4).
- **Identity:** `id`.
- **Kind attribute:** `domain` or `presentational`. Set at
  mint time based on the upstream declaration.
- **Foundation attribute:** `true` or `false`. Set at mint
  time; §4.1 covers the rule.
- **Handle:** `name`, `kind`, role, api_intent, plus the
  comparch-produced fragments (techspec, pubapi, privapi).
- **Draft:** none — mint target. Content is authored by
  the comparch tier via `produces:` (see §1.4 tail).
- **Generator:** none.

### 1.4 `subcomp` — subcomponents

Subcomponents are a structural position, not a separate
tier kind. A `comp_*` whose parent is another `comp_*` is
a subcomponent. Same ID prefix, same field shape, same
handle — the distinction is structural. Depth cap at
two levels (§4.2) prevents sub-subcomponents.

Content for both components and subcomponents is produced
by tier-level architecture docs:

- **Comparch** (`per(comp)` at the top level) produces
  `techspec`, `pubapi`, `privapi`, `policies`, `deps`
  fragments on its parent comp, plus fanout children
  (new subcomponents), plus `policy_application` edges
  against the comp's declared subresponsibilities.
- **Subcomparch** (`per(subcomp)`) produces the same
  fragments (minus `policies` — subcomponents don't mint
  new policies; §4.2 tail) on its parent subcomp. Leaf
  tier — no further decomposition.

Both comparch and subcomparch:

- **Scope:** singleton per their target `comp`.
- **Identity:** `id`.
- **Handle:** summary of the comp's role + API intent; the
  fragments it wrote on the comp are read via the comp's
  handle.
- **Draft:** yes; grammar in bundle's
  `scaffold/tiers/comparch/grammar.xml` etc. (root
  `<comparch>` / `<subcomparch>`).
- **Generator:** `llm`.

### 1.5 `impl` — implementation leaves

Each subcomponent and each un-fanned-out top-level
component gets exactly one `impl_*` node that carries the
detailed design and build content the arch doc deliberately
abstracts away. Impls map to folders on disk via the
manifest (§6).

- **Scope:** `singleton_under(comp)` where `comp` is a
  leaf (a subcomponent, or an un-fanned-out top-level
  component).
- **Identity:** `id`.
- **Handle:** content summary, territory (`{repository,
  folder}` tuple).
- **Draft:** yes; grammar declares the impl doc shape
  (implementation overview, data models, interfaces, etc.
  — see bundle's `scaffold/tiers/impl/grammar.xml`).
- **Generator:** `llm` for the design doc; the actual
  code diff is produced by the `plan` and `code` tiers
  below.

### 1.6 `plan` — per-impl plan nodes

Each impl has one `plan_*` that translates impl-level
intent into a concrete list of code changes. Plans are the
step between "what we're building" (impl) and "the actual
diff" (code).

- **Scope:** `singleton_under(impl)`.
- **Identity:** `id`.
- **Handle:** the structured change list (files, functions,
  types to add/modify/delete).
- **Draft:** yes; grammar declares the plan shape.
- **Generator:** `llm`, reading the impl + surrounding
  context.

### 1.7 `policy` — cross-cutting constraints

Policies are enforced-usage rules — "every LLM call records
telemetry," "every DB write goes through the reducer." Full
treatment in §5; this entry just catalogues the tier.

- **Scope:** children of `sysarch` (top-level policies) or
  of a specific comparch (component-local policies).
- **Identity:** `id`.
- **Handle:** trigger phrase, required responsibility,
  rationale.
- **Draft:** none — minted from the `<policies>` fragment
  of the parent arch doc.
- **Generator:** none.

### 1.8 `fanin` — domain fan-in synthesis

Every domain component with subcomponents gets a `fanin_*`
node that aggregates the subtree's actual exposed surface
for presentational counterparts to read. Full treatment in
§4.4.

- **Scope:** `singleton_under(comp)` where
  `comp.kind == domain AND count(comp.subcomponents) > 0`.
- **Identity:** `id`.
- **Handle:** the aggregated synthesis content.
- **Draft:** yes; grammar declares the synthesis shape.
- **Generator:** `synthesis` (platform-shipped; A.3.2).

### 1.9 `ref` — project reference documents

First-class supplemental content — DSL specs, deployment
runbooks, cross-component invariants, design-rationale
memos. Full treatment in §8.

- **Scope:** `parent_id = null`; project-scoped.
- **Identity:** `id`.
- **Handle:** title, body, outgoing `see-also` references.
- **Draft:** yes; grammar is a `<reference>` root with
  `<title>`, `<body>`, optional `<see-also>`.
- **Generator:** `llm`, regen-on-feedback.

### 1.10 `vocab` — project vocabulary terms

Project-specific jargon with definitions. Full treatment
in §7.

- **Scope:** `parent_id = null` (project-level) or
  `parent_id = feat_*` (feature-local).
- **Identity:** `id`.
- **Handle:** name, definition, disambiguation note, see-
  also references.
- **Draft:** yes; grammar is a `<vocab-entry>` root.
- **Generator:** `llm` for initial mint and edits; user
  can also author directly via the `CreateVocabEntry`
  instruction.

### 1.11 Bootstrap tiers

Bootstrap tiers are the authored-prose nodes whose
approval mints structured children (platform §A.7.1). Five
of them in the default bundle, each a project-singleton:

- **`expansion`** — the per-project prose decomposition of
  the raw input into features. Approval mints `feat_*`
  children and `vocab_*` entries (if the user wrote a
  `<vocabulary>` section). Read-only after initial
  approval in the scaffolding pass; re-editable via
  feature-request or refactor flows.
- **`reqs`** — the top-level requirements bootstrap.
  Decomposes the approved feature set into top-level
  `resp_*` nodes and mints `feat→resp` decomposition
  edges. Read-only after approval.
- **`sysarch`** — the system architecture bootstrap.
  Produces the component graph: top-level `comp_*`
  instances (with the foundation comp), a project-level
  `<technical-specification>` section, `<policies>` that
  mint top-level `policy_*` nodes, `<dependencies>` that
  mint `dependency` edges (including speculative
  policy-induced deps), and `<domain-parents>` that mint
  `domain_parent` edges. Also mints one `subreqs_*`
  bootstrap per top-level component. Read-only after
  approval.
- **`subreqs`** — per top-level component, decomposes the
  component's top-level responsibilities into
  subresponsibilities. Mints `resp_*` subresp children
  and `top_level_resp → subresp` decomposition edges.
  Read-only after approval.
- **`manifest`** — project-singleton file-territory
  mapping from repository paths to owning impl nodes.
  Regenerated by the code-generation pipeline rather than
  authored by the user; lives in the event log like every
  other node. See §6 for territory.

### 1.12 `changeplan` — per-flow-run intent nodes

Change plans persist per-flow-run-per-affected-tier as
reviewable prose artifacts documenting "what this change
means at this tier." They're the unified change-plan and
implicated-children-split artifact flows produce at every
planning visit (platform §A.4.2).

- **Scope:** per flow visit; singleton per (flow_run,
  target_node).
- **Identity:** `id`.
- **Handle:** intent prose, `<implicated-children>`,
  optional `<additions>` / `<structural-ops>` /
  `<assessment>`.
- **Draft:** yes; grammar varies per flow.
- **Generator:** `llm`.

Change plans are explicitly **not structural DAG nodes** —
nothing depends on them via `dependency` edges, and they
don't project structured children on approval. They're
review surfaces that document intent, persisted for
provenance (A.4.3).

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
