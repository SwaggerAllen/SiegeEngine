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

Five named edge instances, each typed against one of the
platform's five edge types (platform §A.3.2). The bundle
declares the specific source/target tiers and cardinality;
the platform handles the type-level semantics (cycle
detection, readiness contribution, etc.).

### 2.1 `dependency`

Typed as the platform's `dependency`. Represents "A's
public surface reaches into B's public surface" —
component A imports or calls something from B.

- **Shape:** `comp_* → comp_*` (both top-level and subcomp).
- **Cardinality:** unbounded; a comp can depend on any
  number of siblings.
- **Declared in:** `comparch.draft.dependencies[]` for
  top-level comp deps; `comparch.draft.sub_dependencies[]`
  for subcomp-to-subcomp within the same parent.
- **Graph constraint:** `acyclic`, `no_self_loop`.
- **Scope:** top-level deps are project-wide; subcomp deps
  are scoped `within(comparch)` (both endpoints in the
  same parent's fanout).
- **Context contribution:** a dependent's regen context
  walks `self.dependency → target.handle.fragments[pubapi]`
  — dependents see only the pubapi fragment, not the whole
  arch doc.

Policy-induced dependency edges (see §5) are declared in
the same `<dependencies>` section — bundles don't distinguish
them from ordinary deps at the edge level. The distinction
lives in the `<policies>` fragment that motivated the edge.

### 2.2 `domain_parent`

Typed as the platform's `synthesis` edge. "This
presentational component is a primary view into this
domain component's fan-in aggregator" — the presentational
subscribes to the domain's synthesis handle.

- **Shape:** `comp_* → comp_*` where source is
  presentational and target is domain.
- **Cardinality:** a presentational comp may have multiple
  domain parents; a domain comp may have multiple
  presentational counterparts.
- **Declared in:** `sysarch.draft.domain_parents[]`.
- **Graph constraint:** cross-kind
  (`source.kind == presentational AND target.kind ==
  domain`).
- **Context contribution:** presentational comps' regen
  context walks `self.domain_parent → target.synthesis`,
  pulling the domain's fan-in aggregate rather than the
  top-down spec. §4.4 covers why.

### 2.3 `policy_application`

Typed as the platform's `policy_application`. "This policy
applies to this component at these trigger sites."

- **Shape:** `policy_* → comp_*`.
- **Cardinality:** a policy can apply to many components;
  a component can be subject to many policies.
- **Declared in:** `comparch.draft.policy_applications[]`
  (component-architecture approval, not policy mint).
  Declared at comparch time rather than policy mint
  because applicability needs the full techspec and
  subresps as input — see §5.
- **Graph constraint:** reachability (the policy's
  required responsibility must be reachable from the
  target component via dep edges, so the capability the
  policy requires is actually accessible).
- **Context contribution:** when a comp's impl is
  generating code, its context walks
  `self.policy_application.inverse → source.handle` to
  see which policies apply.

### 2.4 `decomposition`

Typed as the platform's `reference`. Many-to-many
projection edges; two conventions share the type:

- **`feat_* → resp_*`** — the feature implicates the
  top-level responsibility. Emitted at reqs-approve time
  based on the `<feature-implications>` section of the
  reqs bootstrap.
- **`resp_* → resp_*`** (top-level → subresp) — the
  top-level responsibility decomposes into this subresp
  within its owning component. Emitted at subreqs-approve
  time.

Both endpoint kinds use the tier-agnostic `resp_*`
prefix; the distinction between top-level and subresp
lives in the nodes' parent assignments (§1.2).

- **Graph constraint:** acyclic (a resp can't decompose
  into an ancestor resp).
- **Context contribution:** various — features read their
  implicated resps; subreqs regens read top-level resps;
  comparch regens read their component's implicated resps.

### 2.5 `reference`

Typed as the platform's `reference`. General-purpose
advisory-context edge any node can use to declare "during
my regen, also read this node's handle."

- **Shape:** `any_node → any_node`.
- **Cardinality:** unbounded.
- **Declared in:** `CreateReference` and `AddReference`
  instructions (user-driven), plus bundle-seeded refs at
  project creation (§8, platform §A.11.5).
- **Graph constraint:** acyclic.
- **Context contribution:** the source's regen context
  walks the edge and dispatches on target tier —
  `ref_*` → full body, `comp_*` → pubapi fragment,
  `policy_*` → rationale, etc. Both outgoing and inbound
  reference edges contribute to a node's context.

## 3. Fragments and transclusion

Component and subcomponent architecture docs are not
free-form prose. They have a stable section structure the
model can parse, because sibling components' regeneration
prompts pull each other's API surfaces out of these docs
at context-assembly time, and stuffing the entire
dependency doc into every dependent's prompt would blow up
the context budget as the project grows.

### 3.1 Section vocabulary and order

Five fragment kinds, each a section in a parseable arch
doc, **in this order**:

- **`<technical-specification>`** (kind: `techspec`) — the
  high-level "what are we building, with what" for this
  component: technologies, major algorithmic choices,
  cross-cutting invariants. Deliberately abstract — no
  responsibility assignments, no per-subcomponent
  sequencing. Its job is to let the LLM *think* about
  the shape of the thing before it decomposes. A change
  to a child's implementation does not regenerate the
  techspec; the spec propagates downward, not upward.
- **`<public-surface>`** (kind: `pubapi`) — the
  component's API. Types, function signatures, methods,
  events — anything a dependent is allowed to reach for.
  This is what gets extracted and handed to dependents at
  regen time.
- **`<private-surface>`** (kind: `privapi`) — internal
  types and helpers. Visible to the component's own
  subcomponents during their regen, but not to sibling
  dependents.
- **`<policies>`** (kind: `policies`) — the policies this
  arch doc mints, each a structured tuple of trigger +
  required responsibility + rationale. Comes **before**
  `<dependencies>` because a policy can induce a dep edge;
  the LLM must decide which policies apply before
  enumerating deps, so policy-induced deps land naturally
  in `<dependencies>` rather than being backfilled.
  Subcomponent arch docs omit this section — they
  introduce no new responsibilities to target.
- **`<dependencies>`** (kind: `deps`) — the list of
  sibling components this one reaches for, by stable ID.
  Parseable separately because it feeds dependency-edge
  edits and cycle detection. Always generated *after*
  `<policies>` in the same LLM call.

The sysarch node has its own `<technical-specification>`
section at the top-level tier, where project-wide
concerns like language choice and runtime targets live.
Subordinate tech specs inherit those constraints; child
tech specs may narrow the parent's choices but not
contradict them.

**Fragments are transcluded.** Each parseable section is
a **fragment** with its own stable ID of the form
`<owner_id>_<fragment_kind>` — e.g.,
`comp_a3f7k2m9_pubapi` is the public surface fragment
owned by component `comp_a3f7k2m9`. Fragment kinds are
required to be single-token (no underscores inside a kind
name); the parser splits on the last underscore, so
`<owner_id>` stays unambiguous.

When a dependent component needs to know what its upstream
exposes, its regen prompt pulls the upstream's `pubapi`
fragment by ID. The upstream's full arch doc never enters
the prompt — only the fragment. This is the load-bearing
scoping that keeps prompts bounded as the project grows,
and it also makes fragment-level diffs the natural unit of
propagation: a change confined to `<technical-
specification>` does not invalidate dependents that only
read the `pubapi` fragment.

Inside `<public-surface>` and `<private-surface>`,
code-shaped content lives in language-agnostic fenced code
blocks. The parser doesn't inspect the code — it just
pulls the tagged section whole. This means the generated
code can be in any language and the fragment machinery
doesn't have to care.

### 3.2 Fragment-level diff as drift signal

**Disagreement detection is a fragment diff.** If the
sysarch claimed a component would expose one API and the
component arch ended up exposing a different one, the
sysarch's copy of `comp_X_pubapi` (speculative, written at
sysarch time) and the component arch's copy (authoritative,
written at comparch time) diverge. That is the drift
signal, surfaced naturally as a diff over two fragment
instances with the same ID.

The bundle doesn't need a separate "drift detection"
mechanism — fragment equality against multiple authoritative
sources handles it. When the sysarch-declared pubapi and
the comparch-authored pubapi differ, the UI flags both; the
reviewer decides whether to revise sysarch downstream or
revise comparch upward.

## 4. Structural rules

### 4.1 Foundation components

Every level of the structural tree has **shared files at
its root** — build config, package init, cross-cutting
utilities, top-level entry points — that don't logically
belong to any one child. Without a dedicated owner, those
files are orphaned by the file manifest and by code
generation: no impl node produces them, no plan node
touches them, and the resulting project isn't buildable.

To fix this by construction, every structural decomposition
pass is required to mint a **foundation component** as one
of its children:

- **Sysarch** always includes a foundation component in
  its top-level component list. Its territory covers the
  project's root folder minus whatever the other top-level
  components claim.
- **Each component-architecture pass** that decomposes a
  component into subcomponents includes a foundation
  subcomponent, **unless the component being decomposed is
  itself a foundation component**.

**Foundations don't nest.** When a foundation component —
top-level or sub — is itself decomposed by a component-
architecture pass, that pass does **not** mint another
foundation subcomponent inside it. Instead, the generation
prompt is told to **divide the foundation's territory
exhaustively**: every file the foundation owned must be
claimed by one of the concrete subcomponents it mints,
with no residual catch-all. The reason is that "foundation"
means "catch-all at this level"; a sub-foundation inside a
foundation would be the catch-all of the catch-all, which
collapses to the original.

Whether a component is a foundation is persisted as a
first-class attribute on the comp node, set at mint time
by the sysarch and comparch mint handlers based on the
parsed foundation marker in the upstream arch doc.
Downstream passes read it directly rather than re-parsing
upstream content.

A foundation component is a normal `comp_*` in every other
respect — it has its own responsibilities, its own
fragments, its own dependencies, and it can have
subcomponents if it decomposes further (subject to the
depth cap and the nesting carve-out). Naming is free — the
LLM defaults to "Foundation" but the user can rename.

The foundation rule guarantees three things: manifest
coverage (every file at every level has an owner, because
foundations are the explicit catch-all remainder), code-
generation buildability (the top-level foundation owns
build config and entry points so the first code-gen pass
produces a compilable project), and a natural home for
cross-cutting utilities (shared types used by multiple
subcomponents land in the foundation without having to be
artificially extracted as a standalone top-level component).

### 4.2 Subcomponent depth cap

The `comp_*` tier is tier-agnostic for ID purposes (§1.3) —
promotion and demotion between top-level components and
subcomponents must not change the ID, so both share the
prefix. But the structural tree is **hard-capped at two
levels**. A `comp_*` whose parent is another `comp_*`
cannot itself be the parent of any `comp_*`. In other
words: component → subcomponent → impl is the full allowed
structural chain; no sub-subcomponents, ever.

Three-level component trees are harder to review, harder
to render, and add only marginal expressiveness beyond
what "promote the middle layer to its own top-level
component" already provides. Promotion is a single
operation in the refactor flow's structural-ops list, and
it's the right answer whenever a subcomponent's
decomposition would need its own children.

The cap is enforced by the reducer on every structural
event whose target tier is `comp` — `NodeCreated`,
`NodeReparented`, `NodePromoted`, `NodeDemoted`. If the
chosen parent is itself a `comp_*` whose own parent is a
`comp_*`, the event is rejected before it's applied. The
comparch regen prompt is also told about the cap explicitly,
with the escape hatch framed as: "if decomposition would
require three levels, stop and recommend promoting the
middle layer to a top-level component."

Knock-on consequences:

- **Subresponsibilities are a leaf responsibility tier.**
  Subresp → subcomp is the full story; there are no sub-
  subresps.
- **Fan-in nodes never nest** (§4.4). A fan-in synthesizes
  across one component's direct subcomponents, which is
  also the only structural possibility.
- **Policies have exactly two generation tiers**, matching
  the two tiers where responsibilities are minted.
  Top-level policies live in the sysarch's `<policies>`
  fragment; component-local policies live in each
  component's arch-doc `<policies>` fragment. No recursive
  policy-generation pass.
- **Subcomparch docs omit the `<policies>` section.**
  Subcomponents are leaves; there are no new
  responsibilities to target with new policies and no
  subtree to scope new triggers against.

### 4.3 Unified domain/presentational DAG

There is no separate domain graph and presentational graph.
Domain and presentational nodes share the same shape —
feature → responsibility → component → subcomponent →
impl — and the distinction is a `kind` tag on the node,
not a different data model. Presentational nodes are
strictly layered *after* domain nodes in the generation
order: a presentational component can depend on a domain
component's public surface, but a domain component cannot
depend on a presentational one.

- **Dependency edges cross kinds.** A presentational
  component depending on a domain component via the
  latter's public surface is the normal "I import your
  API" edge and behaves the same regardless of the kind
  distinction.
- **Domain-parent edges mark primary views.** These are
  `presentational → domain`, 1:N, and indicate the domain
  component(s) this presentational component is a primary
  view *into*. Semantics differ from dependency: a primary
  view needs to reflect what was actually built at the
  domain side, not just the API contract, which is why
  `domain_parent` edges feed fan-in synthesis nodes (§4.4)
  while dependency edges feed only public surfaces.
- **Sibling means "same parent / same level," not "same
  kind."** A presentational component can have domain
  components as dependency siblings in the context-assembly
  sense. A notifications UI component, for example, may
  have no domain parent (notifications isn't a primary
  view into a single domain concept) but depends on
  several domain components for the data it shows.
- **Admin surfaces, docs pages, and UI features are
  regular presentational features.** They are not a third
  node kind. Each such surface is a presentational feature
  with its own domain-parent edges where they make sense
  and plain dependency edges everywhere else.

Presentational generation prompts read two kinds of
context from the domain side: the domain component's spec
(the top-down intent) and the domain component's fan-in
synthesis (the bottom-up "what exists"). If those two
disagree, that's a meaningful signal that the domain side
has drifted from its own contract, and the presentational
regen is the natural place for it to surface.

### 4.4 Domain fan-in synthesis

Domain-parent edges carry far more context than plain
dependency edges. A dependent that just imports an API only
needs the public surface; a presentational node that is a
primary view into a domain component needs to faithfully
reflect what was actually built underneath, not just the
contract.

To carry that load without inflating presentational regen
prompts, **every domain component with subcomponents gets
a fan-in synthesis node** sitting at the bottom of its
subtree, regardless of whether a presentational counterpart
currently exists. Always-minting is a deliberate
simplification: adding a domain-parent edge later never
has to retroactively materialize a fan-in, and the minting
rule is purely a function of the domain subtree shape.
The cost is a few extra regens for fan-ins nobody is
reading yet, which is acceptable.

Domain components without subcomponents don't need a
fan-in — their own implementation node already is the
synthesis, and a presentational counterpart reads it
directly.

```
domain feature
  → domain responsibility
    → domain component (spec / contract)
      → domain subcomponents
        → subcomponent implementations
          → fan-in synthesis           ← bottom of the domain accordion
            → presentational counterpart (cross-tree, via domain_parent edge)
```

Properties of fan-in nodes:

- **Strictly downstream of subcomponent implementations.**
  They synthesize "given these subcomponent
  implementations, here is what this component actually
  exposes and does at the component level." They never
  read their own domain component's spec directly — that
  would be circular.
- **Feed only presentational counterparts.** Current or
  future, via domain-parent edges. Fan-ins are never read
  by their own domain component, so domain-side
  regeneration stays single-pass top-down with no upward
  propagation.
- **Real projection nodes with their own diffs and
  staleness.** When a subcomponent implementation changes,
  the fan-in regenerates, and *its* diff is what reaches
  the presentational side. A presentational node reading
  a fan-in never sees N subcomponent diffs directly — its
  input set is bounded no matter how big the domain
  subtree grows.
- **One fan-in per domain component, not one per level.**
  The synthesis collects the entire subtree below the
  component in a single rollup. Subcomponents don't get
  their own fan-ins.
- **Not reviewed directly.** Fan-ins are mechanical
  synthesis; real edits land at the subcomponent
  implementations below them, and "does this reflect what
  was built" is actually checked at the presentational
  counterpart. Reviewing the fan-in itself would be
  triple-counting the same diff. Fan-ins are excluded
  from review scoping.
- **Always-present even without a presentational
  counterpart.** Minted unconditionally for any domain
  component with subcomponents. Adding a domain-parent
  edge later is then a pure edit, not a mint-on-the-fly.

**Scheduling invariants.** Two gates matter:

- **First-pass gate.** A fan-in generates for the first
  time when every subcomponent's impl is approved and
  populated. Before first-pass, partial impl coverage
  leaves the gate closed. This falls out of the
  synthesis edge's platform-shipped readiness rule
  (§A.3.2).
- **Presentational comparch gate.** A presentational
  comp's comparch waits until every one of its
  `domain_parent` targets has a populated fan-in node.
  This falls out of the presentational tier's context
  walk `self.domain_parent → target.synthesis` failing to
  resolve until the synthesis exists.

Both gates are reactive-schema defaults, not special-case
bundle logic.

## 5. Policies

Some content isn't a capability, it's a constraint: "every
LLM call records telemetry," "every DB write goes through
the reducer," "every route checks the session." These
aren't things *one* component does — they're things
*every* component does, and they need to be both **stated**
(so the LLM writing an implementation knows about them) and
**reviewable** (so a human can confirm a cross-cutting
invariant still holds).

The capability a policy requires is still modeled as a
normal component — `TelemetryService`, the reducer, the
session check — reached via ordinary dependency edges.
What's new is the *policy itself*: the statement that the
capability must actually be used at every trigger site.

### 5.1 Shape of a policy

A `policy_*` node carries three fields:

- **`trigger`** — a short semantic phrase identifying the
  site type where the policy applies: "any LLM call,"
  "any DB write," "any presentational route handler."
  The policy-application pass reads this and decides
  whether the trigger plausibly occurs in a given
  component based on that component's techspec, public
  surface, and subresponsibilities. It's semantic, not a
  structural identifier, so the trigger vocabulary doesn't
  need a central registry — a new kind of cross-cutting
  concern is just a new policy with new trigger wording.
- **`required`** — the ID of the responsibility (`resp_*`)
  that must be fulfilled at every trigger site. Policies
  reference responsibilities, not components directly,
  because the resp → comp 1:1 mapping gives the
  application pass the concrete component to call while
  keeping the policy stable across component refactors:
  if `TelemetryService` gets merged or split, the
  `resp_telemetry` it fulfills moves with it and the
  policy wording doesn't change.
- **`rationale`** — prose explaining why the policy
  exists. Shown in review and included in regen prompts
  so the LLM understands intent. Carries real weight in
  the application decision — "record latency for anything
  a user waits on" tells the LLM what kind of trigger
  sites to look for.

Policies live in the `<policies>` fragment of an arch doc.
On approval, the reducer parses the fragment and projects
each entry into a `policy_*` node, the same way the
`<dependencies>` fragment projects into dependency edges.
The fragment is the authoring surface; the node is the
identity that `policy_application` edges reference.

### 5.2 Two generation tiers

Matching the two responsibility tiers:

1. **Top-level policies** — generated as part of the
   sysarch joint-reasoning pass, alongside components,
   API intent, and dep edges. Live in the sysarch's
   `<policies>` fragment. Trigger phrases can match
   against the full component set. The `required` field
   references top-level `resp_*` nodes minted by the
   requirements bootstrap.
2. **Component-local policies** — generated as part of
   each component's arch-doc pass, alongside
   subcomponents and that component's deps. Live in the
   component arch doc's `<policies>` fragment. Trigger
   phrases match only against components in the minting
   component's subtree. The `required` field references
   either top-level responsibilities or this component's
   own subresponsibilities, whichever the obligation
   actually needs.

Subcomparch docs have no `<policies>` section —
subcomponents are leaves; no new responsibilities to
target with new policies and no subtree to scope new
triggers against.

### 5.3 Application at component-architecture time

"Does this policy apply to this component?" is an LLM
decision that needs the candidate component's full
techspec, public surface, and subresponsibilities
available as input. At sysarch approval time, the
sysarch's per-component summary is deliberately high-level
— role plus API intent only — because the whole point of
the sysarch/component-arch split is that sysarch entries
stay stable as subcomponents iterate. At that level of
detail, the application pass cannot confidently answer
"does this component have trigger X."

So the application pass runs at component-architecture
generation time:

1. **Sysarch generation** produces `<policies>` in its
   output as normal. On approval, `policy_*` nodes are
   projected from the fragment. **No `policy_application`
   edges are emitted yet for top-level policies.** Policy
   nodes exist; they have no application edges.
2. **Sysarch emits speculative policy-induced dep edges**
   in its `<dependencies>` section, based on role-level
   inference against the per-component summaries it does
   have ("this component's role involves generating
   content, so it probably needs `TelemetryService`").
   Best-effort. A missed dep at this stage can be patched
   at component-architecture time.
3. **Component architecture generation** receives the
   full list of top-level `policy_*` nodes as candidates
   in its regen prompt. The LLM reads the component's
   techspec, subresponsibilities, and public surface, and
   decides for this specific component which policies
   actually apply. Component-local policies minted in the
   same pass go through the same application step,
   scoped to the component's own subtree.
4. **`policy_application` edges are emitted on
   component-architecture approval**, one per (policy,
   this-component) pair the LLM marked as applicable. The
   component arch's own `<dependencies>` list also gets a
   chance to add any policy-induced dep that sysarch's
   first pass missed.

### 5.4 Policy-induced dependency edges

A policy that says "at any trigger site, fulfill
responsibility X" implicitly requires every applicable
component to depend on whichever component owns X. Those
dep edges have to exist or the generated code cannot reach
the required capability. This is why `<policies>` comes
*before* `<dependencies>` in the arch-doc section order:
the LLM is expected to reason about policies first and
then emit a dependency list that already reflects
policy-induced edges.

Policy-induced deps are ordinary `dependency` edges — the
bundle doesn't distinguish them from user-intended deps at
the edge level. The distinction lives in the `<policies>`
fragment that motivated each edge; a reviewer can trace a
dep back to the policy that implied it by looking at the
fragment.

### 5.5 Application edges are editable but not formally reviewed

The instruction vocabulary includes operations to add or
remove a policy application for cases where the LLM's
decision is wrong (false positive or false negative). User
overrides are normal structural edits.

Application edges aren't reviewed separately because the
*policies themselves* are reviewable — they're part of the
arch doc's `<policies>` fragment — and if a policy turns
out to be too broad or too narrow, the fix is to edit the
policy wording or its trigger, not the edges one by one.

## 6. Ownership and repository territory

Ownership-as-scoped-role is a platform mechanism (spec
§A.6); this section covers the default bundle's specific
use of it and the territory model that pairs with it for
code delivery.

### 6.1 Ownership assignment at fan-out

When the sysarch fan-out mints top-level components, or a
comparch fan-out mints subcomponents, the approval that
commits the mint also captures owner assignments for the
new children. Ownership is part of the approval, not a
separate step. The UI surfaces owner assignment inline with
the implicated-children checklist: reviewer sees each new
comp and picks an owner from the project's member list.

A component may transfer ownership later via the scoped-
role system's normal delegation mechanics (§A.6.3). The
default bundle doesn't impose a separate ownership-edit
workflow.

### 6.2 Non-owned node kinds

Features, responsibilities, and policies are project-level
artifacts without single natural owners. They're reviewed
by whoever owns the component(s) that decompose them, and
permission checks against those artifacts fall through to
project-scoped roles (`admin`, `reviewer`).

Refs (§8) and vocab entries (§7) are project-scoped; their
review routes to project-scoped roles the same way.

### 6.3 Repository and folder territory

For the code-generation side of the system, each leaf maps
to a `{repository, folder}` pair called its **territory**.
For the MVP, all leaves within a project target a single
repository (monorepo assumption), but the data model
supports multi-repo via the `{repository, folder}` mapping
so multi-repo projects are a post-MVP extension without a
data-model change.

Within a repository, each impl node corresponds to a
folder — the leaf's territory — and is the only node
allowed to write files in that folder. This gives a direct,
deterministic mapping between the structured model and the
codebase. The mapping is enforced in code-generation
prompts and in the AI sandbox (spec §A.18), which prevents
a leaf's coding assistant from reading or writing files
outside its territory.

The top-level foundation component's territory is the
project's root folder minus everything the other top-level
components claim. Each nested level's foundation
subcomponent likewise owns its parent's root folder minus
its siblings. This is how the file manifest achieves full
coverage: every file at every level has an owning impl
node because the foundation rule (§4.1) defines the
catch-all remainder explicitly at every nesting level.

### 6.4 The manifest tier

The `manifest_*` node (project singleton, §1.11) is the
authoritative mapping from folder path to owning leaf. The
manifest is minted and regenerated by the code-generation
passes, not authored directly by the user. When a
structural operation reshapes the component tree (split,
merge, reparent, promote, demote), the manifest is
regenerated as part of the same flow so territory stays
aligned with the tree.

An orphaned folder — one not claimed by any leaf — is a
manifest-level error surfaced in the admin tools. The UI
flags manifests with coverage gaps so the reviewer can
either fix the foundation that should have claimed the
folder or explicitly delete the orphaned files.

### 6.5 The `git_commit` generator tie-in

Tiers whose content ships as code — `impl`, `plan`, `code`
— declare `generator: git_commit` (platform §A.16.1). The
generator reads the tier's territory and writes diffs to
`{repository, folder}` on the flow's branch, one commit
per tier instance. Territory is how the generator knows
where to write; ownership is how the platform knows whom
to route the resulting PR review to.

## 7. Project vocabulary

Every project has jargon. "Boulder" in one project is a
container with internal structure; "boulder" in another is
a blocker issue that can't be moved past. "Tranche" in a
finance product is a debt-security slice; in an invoicing
pipeline it might be a time-bounded batch of work. Generic
LLM priors fight project-specific meanings at every
regeneration where the project's definition isn't fresh in
prompt context, and when the priors fight, the LLM quietly
substitutes its defaults and produces silent drift toward
generic meanings.

Per-node regeneration with bounded context windows is
exactly the environment where definitions are most easily
forgotten, and the cost of forgetting is architectural
decay. A dedicated vocabulary layer makes project-specific
term definitions structured, addressable, and
always-included in regeneration context.

### 7.1 Vocabulary entries as nodes

Vocab entries are **entities, not content** — they have
names, content, edges to other entities (cross-references
between terms, planned as a post-MVP extension), their own
edit/review lifecycles, and their own place in the
project's audit trail. Modeling them as a node tier rather
than as a fragment on another node is what gives them all
of that: fragments are sections of a larger document,
reviewed as part of their owner, and they can't participate
in edges. Vocab entries can, and need to.

### 7.2 Scope via `parent_id`

A vocab node with `parent_id = null` is a **project-level
term** — every regeneration at every tier sees it. A vocab
node with `parent_id` set to a `feat_*` id is a
**feature-local term** — only regenerations reachable from
that feature via decomposition see it.

The reducer enforces this directly: a `vocab_*` node's
parent, if set, must be a `feat_*`. Parenting vocab under
a component, responsibility, or any other tier is rejected
at event-apply time, because scoping vocab below the
feature layer would leak project-specific terms into
arbitrary internal decomposition and defeat the purpose of
having a coherent project-wide vocabulary.

### 7.3 Promotion between scopes is reparent

A feature-local term that turns out to be useful
project-wide gets promoted with a `NodeReparented(vocab_id,
new_parent_id=null)` instruction. The term keeps its ID,
its content, its edit history, and (once cross-reference
edges land) its `vocab_reference` edges. This is the same
reparent primitive used for component promotion; vocab
gets it for free.

### 7.4 Content shape is structured XML

Each vocab entry's `Node.content` holds a `<vocab-entry>`
block with three children in fixed order:

- `<definition>` (required, non-empty) — prose describing
  the term.
- `<disambiguation>` (optional) — a "not to be confused
  with" note that directly counteracts LLM priors.
  Strongly encouraged for any term whose project-specific
  meaning diverges from a common one.
- `<see-also>` (optional) — a list of `<ref name="..."/>`
  or `<ref to="vocab_..."/>` elements cross-referencing
  other terms.

The grammar is parseable, validated at authoring time, and
fits the same family as component and subcomponent arch
docs. Storing XML from day one means a post-MVP
`vocab_reference` edge type — emitting `EdgeCreated(
edge_type="vocab_reference", source=this_vocab_id,
target=ref_id)` for each resolved reference — becomes a
one-function follow-up rather than a retrofitted parser
over prose.

### 7.5 Render-time transformation for prompts

The storage format is XML; the prompt format is prose. At
context-assembly time, a formatter walks each vocab entry's
stored XML and renders it as human-readable text:
"Definition: ... / Disambiguation: ... / See also: term1,
term2." The LLM sees readable definitions rather than raw
tags.

This decouples storage from prompt-friendliness —
extending the XML grammar (for categories, deprecation
flags, alternate names, anything else we decide vocab
entries should carry) requires only updating the formatter
to include new fields in the prose rendering, with no
stored-content rewrite or migration. Prompt tokens are
too expensive to spend on XML syntax the LLM doesn't need.

### 7.6 Minting

Vocabulary is projected from the expansion bootstrap. The
expansion output gains an optional `<vocabulary>` section
sibling to `<features>`, containing `<term>` elements with
`name`, `scope`, and (when scope is feature) `feature-alias`
attributes. Each `<term>` contains a single `<vocab-entry>`
inner block matching the grammar above.

On expansion approval, `feat_*` and `vocab_*` nodes mint
in the same transaction; the alias-to-id map built during
feature minting resolves `feature-alias` attributes on
vocab entries to their target `parent_id` values.

Feature-request and refactor flows that introduce new
jargon also project new vocab entries via the same
mechanism — the flow's phase-zero or planning tiers emit
`<vocabulary>` sections which land as `vocab_*` nodes when
approved.

### 7.7 Context assembly

Every regeneration prompt at every tier sees the project
vocabulary. Project-level entries are always included;
feature-local entries are included for every feature
reachable from the regen target via the decomposition walk
(features the target's subtree serves, computed from the
`feat → resp → comp → resp → comp` chain).

The vocabulary partition has its own context-budget
allocation separate from parent architecture, sibling
pubapis, or change-plan context — vocabulary doesn't
compete with architectural content for budget because the
cost of forgetting a term once is higher than the cost of
including it every time.

### 7.8 Direct user creation outside a flow

The instruction vocabulary includes a `CreateVocabEntry(
name, content, parent_id)` operation so users can add
terms without running a flow. A reviewer who notices a
term that needs definition clicks "add term" in the
vocabulary UI, fills in the name and the `<vocab-entry>`
body (or lets the LLM generate an initial draft from a
one-line prompt), and the instruction flows through the
normal lifecycle. Renaming, reparenting, and deleting a
vocab entry all reuse existing `NodeRenamed` /
`NodeReparented` / `NodeDeleted` instructions.

### 7.9 Exclusion from structural views

Vocabulary is not shown in the decomposition graph, the
component tree, or any other structural visualization.
Vocab entries are not part of the project's architectural
shape — they're metadata about the terms the architecture
uses. The UI surfaces vocabulary through a dedicated
"Vocabulary" tab on the project dashboard, a per-feature
vocab panel on feature detail views, and inline definition
tooltips wherever a known term appears in a rendered
artifact. This keeps the structural view uncluttered and
gives vocabulary its own first-class home.

### 7.10 Out of scope for MVP

- LLM-discovered vocabulary (where the LLM notices it's
  using a term in a specific way and surfaces it as a
  candidate definition for review).
- `vocab_reference` edges as first-class graph entities.
  (They will exist eventually; initial implementation
  stores cross-references as `<see-also>` entries in
  stored XML without emitting edges.)
- Proliferation guardrails for projects that accumulate
  hundreds of terms.
- Automatic linking of vocabulary terms in rendered
  artifact prose.

All straightforward follow-ups; none are load-bearing for
the initial vocabulary layer.

## 8. Project references

Some Catapult projects ship first-class supplemental content
alongside the code their components generate: a DSL spec for
a bundle's custom grammar, an opinionated deployment runbook,
a set of cross-component invariants that multiple components
have to honor, a design-rationale memo the architecture has
to stay consistent with. None of that content fits the tiers
we already have. Components have public surfaces,
responsibilities, and children — specs don't. Vocabulary
entries are term definitions with a specific grammar — specs
are prose, not terms. Fragments are subordinate to an owning
arch doc and cascade on merge or split — a spec shouldn't
get deleted when the component it describes is refactored.

A dedicated tier for **reference documents** lets that
content exist as first-class nodes with their own
lifecycles, their own place in the audit trail, and their
own participation in the regen-context graph.

### 8.1 Refs as their own node tier

Reference documents are modeled as `ref_*` nodes. They are
**entities, not content** — they have titles, bodies,
incoming and outgoing edges, edit/review lifecycles, and
stable IDs. Modeling them as a node tier rather than as a
fragment on another node is what gives them all of that:
fragments are sections of a larger document reviewed as
part of their owner, they cascade on merge, and they can't
participate in edges. Refs can, and need to.

### 8.2 No parent, ever

The reducer enforces a hard invariant: `ref_*` nodes always
have `parent_id = null`. `NodeCreated` and `NodeReparented`
events whose target tier is `ref` and whose parent is
non-null are rejected at event-apply time.

This is a deliberate contrast with vocab (§7), which allows
`parent_id = feat_*` for feature-local scope. Refs don't
have a feature-local case, because their consumers can
cross any tier boundary — a DSL spec might be read by the
bundle-config component, by its subcomponents, by a
presentational component that documents the bundle format,
and by a policy that enforces DSL conformance. Rather than
invent a scope that could accommodate all those cases,
refs use explicit edges to declare their consumers.

### 8.3 Generated and regeneratable, not frozen

Refs run through the same four-state draft panel as
component arch docs: generating → draft → review →
approved. A `generate_ref` job (the `ref` tier's LLM
generator) produces a draft from a user-supplied seed
description plus the referenced-content partition (§8.5),
the user leaves feedback or approves, and approved content
lands on the node.

**Unlike the bootstrap tiers** (expansion, reqs, sysarch,
subreqs, manifest), refs are **not frozen after approval**.
The `UpdateReference(ref_id, feedback)` instruction works
on any ref in any state and triggers a fresh regen. The
freeze rule on bootstrap nodes exists because their
approval mints children that a later edit would desync;
refs don't mint children, so the reason to freeze doesn't
apply. This matches how comparch and subcomparch docs
already work — approved content can be regenerated with
feedback at any time.

### 8.4 Consumption via `reference` edges

Refs participate in the regen-context graph through
`reference` edges — the same general-purpose
advisory-context edge type any node can use (§2.5). A
comp that wants to see a ref's content during regen draws
a `reference` edge from itself to the ref. A ref that
needs upstream context for its own regen — a comp's
pubapi, a policy's rationale, another ref — draws a
`reference` edge from itself to that target.

The context assembler walks these edges in both directions
(outgoing edges pull target content, incoming edges
contribute reverse context), so a single edge between a
comp and a ref gives both sides context from the other. No
special bidirectional semantics — just edges. The
`reference` edge graph must be acyclic, same constraint as
`dependency` edges — a proposed edge that would close a
cycle is rejected at create time.

No reachability walk, no project-wide "always visible"
bucket. Explicit is better than implicit: if a comp needs
the DSL spec, it declares an edge to it.

### 8.5 Edges are user-declared

`CreateReference(seed_description, related_nodes)` takes
one optional list of node IDs. The backend emits one
`reference` edge per entry in the same transaction as the
ref node is minted. Post-creation,
`AddReference(source_id, target_id)` and
`RemoveReference(source_id, target_id)` edit the edge set.
Creating a ref from a comp's detail page pre-fills
`related_nodes` with the current comp.

Bundle-shipped reference material (platform §A.11.5) seeds
refs plus their inbound `reference` edges at project
creation. Once seeded, the refs are regeneratable and
editable through the normal ref lifecycle — project owners
can layer per-project feedback on top of bundle-shipped
content without forking the bundle.

### 8.6 Content shape is parseable XML

Each ref's `Node.content` holds a `<reference>` block with
two required children and one optional child:

- `<title>` — short prose rendered as a heading.
- `<body>` — free-form markdown prose. Not a tight
  grammar, not bullet-structured; just readable text that
  the LLM both authors and reads.
- `<see-also>` (optional) — `<ref to="ref_..."/>` children
  that cross-reference other refs by stable ID.

The grammar is parseable, validated at authoring time, and
fits the same family as component and subcomponent arch
docs. `<see-also>` markers inside stored XML are
human-readable annotations, separate from structural
`reference` edges; a ref author can use either or both.

### 8.7 Render-time transformation for prompts

Storage is XML; prompts are prose. At context-assembly
time, a formatter walks the stored `<reference>` XML and
renders it as `# Title\n\nBody text...` markdown. The LLM
sees readable content without paying prompt tokens for raw
tags. Decoupling storage from prompt format means
extending the grammar later is a formatter change rather
than a stored-content rewrite.

### 8.8 Context assembly

Every regen at every tier sees the `referenced_content`
partition: the rendered content of every node the regen
target has an outgoing `reference` edge to. The context
assembler walks that edge set and dispatches on each
target's tier to extract the right chunk — `ref_*` → full
body, `comp_*` → `pubapi` fragment, `policy_*` →
rationale, etc.

The partition has its own context-budget allocation
separate from vocabulary, sibling pubapis, or policy
candidates — references are content the user has
**explicitly declared this node consumes**, and declared
intent should not have to compete with derived context
for budget.

### 8.9 Staleness propagation

When the staleness ledger lands, it follows `reference`
edges the same way it follows comp→comp `dependency`
edges: editing a node marks every node that references it
as potentially stale. Until the ledger lands, ref edits
are silently non-propagating, the same state of affairs as
comp→comp dep changes today.

### 8.10 Instruction vocabulary

- `CreateReference(seed_description, related_nodes)` —
  creates a ref and its initial edges.
- `UpdateReference(ref_id, feedback)` — triggers a regen
  regardless of approved state.
- `AddReference(source_id, target_id)` — adds an edge.
- `RemoveReference(source_id, target_id)` — removes one.
- `NodeDeleted` (reused) — handles ref deletion.

There is no `NodeReparented` for refs — the parent-is-null
invariant (§8.2) makes it nonsensical.

### 8.11 UI surfaces

Dedicated "References" tab on the project dashboard,
two-pane layout parallel to Vocabulary. Component,
feature, and policy detail pages grow a "Create reference"
affordance that pre-fills `related_nodes` with the current
node. Refs are not shown in the decomposition graph or
component tree — they're supplemental content, not
architectural structure.

### 8.12 Out of scope for MVP

- LLM-driven `reference` edge declaration.
- Project-level "always visible" reference bucket.
- Staleness propagation across `reference` edges
  (deferred to broader staleness work).
- Cross-reference linking in rendered prose.
- LLM-discovered references.
- `<see-also>`-to-edge synchronization.

All straightforward follow-ups.

## 9. Generation plan

### 9.1 Cold-start order

The default bundle's scaffolding behavior (the scaffold's
reactive scheduler running on an approved input doc with
no active flow; §A.4.8) walks the scaffold's tier
dependencies in this order:

1. **Input document** — the raw prose the user brings in.
   The only node the user authors directly.
2. **Feature expansion (`expansion_*`)** — prose
   decomposition of the input into features. Approved as
   a standalone document before any feature nodes exist.
   On approval, `feat_*` nodes project plus any `vocab_*`
   entries from the `<vocabulary>` section.
3. **Requirements (`reqs_*`)** — singleton. Decomposes the
   approved feature set into top-level responsibilities.
   On approval, top-level `resp_*` nodes plus `feat_* →
   resp_*` decomposition edges project.
4. **System architecture (`sysarch_*`)** — singleton.
   Takes the top-level responsibilities and produces the
   component graph: components (including the foundation),
   API intent, top-level policies, dep edges (including
   policy-induced edges), domain-parent edges, and a
   system-level techspec. Approval mints `comp_*` nodes,
   top-level `policy_*` nodes, dep/domain-parent edges,
   and one `subreqs_*` bootstrap per top-level component.
   Top-level policy_application edges are **not** yet
   emitted — they're resolved against each component at
   component-architecture time.
5. **Subrequirements (`subreqs_*`)** — per top-level
   component, minted at sysarch approval. Decomposes the
   component's top-level responsibilities into
   subresponsibilities. On approval, subresp `resp_*`
   children and `top_level_resp → subresp` decomposition
   edges project. Component-architecture generation for a
   component cannot run until its subreqs is approved.
6. **Component architecture docs** — generated in
   dependency topological order after the owning
   component's subreqs is approved. Each consumes the
   sysarch's entry for it (role + API intent), the public
   surfaces of its dependencies, and the pre-minted
   subresponsibilities from step 5. Each also produces
   component-local policies targeting those subresps, and
   on approval is where top-level and component-local
   policies are resolved against this component: the LLM
   reads the now-detailed techspec and subresps and emits
   `policy_application` edges for the policies that
   actually apply. **Presentational components are
   additionally gated on their domain parents' comparch
   completion** — a presentational component's comparch
   cannot start until all its `domain_parent` edge targets
   have approved comparch content, so the presentational
   comparch sees the full domain architecture as context.
7. **Subcomponent architecture docs** — generated in
   dependency topological order within each component.
   Leaf tier — no further decomposition, no `<policies>`
   section. Four fragments only: techspec, pubapi,
   privapi, deps.
8. **Domain fan-in synthesis nodes (`fanin_*`)** — minted
   as part of sysarch for every domain component with
   subcomponents (§4.4). First-pass generation fires once
   every subcomponent's impl is approved and populated.
9. **Implementation nodes (`impl_*`)** — one per
   subcomponent and one per un-fanned-out component.
   Carries the detailed design and build content, distinct
   from the parent's abstract techspec.
10. **Plan nodes (`plan_*`)** — per-impl, translating an
    impl-level intent into a concrete code-change list.
11. **Code** — generated as a final leaf pass, plan by
    plan, in dependency topological order, limited to
    the leaf's territory via the `git_commit` generator.

The **two-tier decomposition split** (reqs/sysarch at the
top, subreqs/comparch per component) is what resolves the
chicken-and-egg of "component A's regen needs component
B's public surface but B hasn't been generated yet." By
committing to top-level responsibilities, then API intent,
then each component's subresponsibilities up front,
dependent components have stable IDs and bounded contracts
to reference even before the downstream components have
been generated in detail. Component architectures then
flesh the intent into full public-surface detail, and the
sysarch's API entry for each component is a transcluded
fragment of the component arch (§3) so drift is detectable
as a fragment diff.

### 9.2 The default bundle as a meaning engine

The generation chain is a **meaning engine** — each tier
produces compressed handles (names, roles, API intents,
pubapi fragments) that downstream tiers reason from
directly, not from the raw input. The chain alternates
**compression**, **expansion**, and **rotation**:

- **Feature expansion** — extraction from raw input into
  named features. Axis transformation: prose → structured
  features.
- **Requirements** — rotation. Features are user-facing
  capabilities; top-level responsibilities are
  system-level obligations. Same underlying substance,
  different axis.
- **Sysarch** — compression. Responsibilities compress
  into the minimal set of components that collectively
  fulfill them, each with an API intent. The first tier
  where the graph gets narrow.
- **Subreqs** — scope-bounded expansion. Each component's
  top-level responsibilities expand into subresponsibilities
  that live inside the component.
- **Comparch** — last compression before impl.
  Subresponsibilities compress into subcomponents with
  pubapis. Final refinement of the API contract.
- **Subcomparch** — leaf articulation, no more tiers to
  correct. The end of the design chain; the impl/plan/code
  that follows is generation rather than design.

Every prompt names its downstream reader, pushes against
category-speak, and frames the tier's transformation type
explicitly. **Handle quality** (meaning-per-token) is the
load-bearing property — if a tier's output is vague, the
fix is in that tier's prompt, not in passing more context
downstream.

The input doc only feeds **extraction tiers** (expansion,
reqs, sysarch). Propagation tiers (comparch, subcomparch,
impl) work from handles only — they see the compressed
representation the extraction tiers produced, not the raw
input. This is the load-bearing scoping that keeps prompts
bounded as the project grows.

### 9.3 Context assembly strategy

At each generation, the context assembler walks the tier's
declared `context:` (§A.3.4) and produces a prose prompt
stitched from multiple named partitions:

- **Parent context** — the tier's direct upstream (its
  parent handle plus the parent's plan if a flow is
  active).
- **Siblings (pubapis only)** — for tiers that read
  sibling dependencies, the upstream's `pubapi` fragment
  (not the whole arch doc).
- **Synthesis views** — fan-in aggregates for
  presentational tiers reading via `domain_parent` edges.
- **Referenced content** — outgoing `reference` edge
  targets, rendered as prose (§8.8).
- **Vocabulary** — project-level vocab always; feature-
  local vocab for features reachable from this tier
  (§7.7).
- **Change plans** — the active flow's plan for this node,
  when a flow is active (platform §A.4.5's
  `context.active_plan`).
- **Feedback** — deferred feedback on this node if any has
  accumulated since the last regen.

Each partition has its own budget allocation. The
assembler selects within each partition by relevance when
a partition's raw content exceeds its budget (e.g., if a
component has 30 sibling dependencies, the assembler pulls
the most-relevant-N pubapis rather than truncating a
single pubapi mid-signature). Budget tuning per-tier is a
bundle configuration knob.

**Fragment-level pulls** (§3.1) are the key to keeping
prompts bounded. A dependent reading its upstream's pubapi
never pulls the upstream's whole arch doc — only the
pubapi fragment. As the project grows, prompts don't grow
with it; they grow only with the **direct** context each
tier reads, which is bounded by the bundle's `context:`
declarations.

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
