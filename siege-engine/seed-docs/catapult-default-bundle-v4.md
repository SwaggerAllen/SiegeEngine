# Catapult — Default bundle reference (v4)

The default bundle is Catapult's graph-of-prompts design system
for AI code generation. It takes a prose input document
describing a software project and produces a layered structured
model — features, responsibilities, components, subcomponents,
implementations — through a reviewable pipeline that terminates
in code committed to a downstream repository.

This document is the **default bundle reference**. The platform
spec (`catapult-spec-v4.md`) describes the bundle at the level
needed to specify the platform; this file holds the bundle's
own tier vocabulary, edge instances, structural rules, and
flow declarations in detail. Implementers read this; bundle
authors read this; the platform itself doesn't.

YAML examples for the bundle's tier, edge, fragment, predicate,
and flow declarations live in the companion file
`catapult-default-bundle-v4-examples.md`.

---

## Overview

### What the default bundle is for

The default bundle is an opinionated answer to "how should AI
generate code well?" The answer it commits to: stage the design
thinking in tiers before any code is produced, review each
tier's output, and let downstream generation consume the
approved upstream handles rather than trying to reason about
the whole project in one prompt. Small well-scoped prompts
produce better output than one massive prompt.

Most Catapult users will encounter this bundle and think of it
as "Catapult." The platform's generality matters because the
bundle's design commitments are choices, not laws — a different
bundle could decompose differently, organize by other axes, or
target other generation targets entirely. But the default
bundle is what ships with Catapult and what most documentation
references.

### Bundle summary at a glance

**Tiers (10 total):**

- Generation tiers (7): `feature_expansion`, `requirements`,
  `sysarch`, `comparch`, `subcomparch`, `impl`, `fanin`.
- Projection-only tiers (2): `comp`, `subcomp` (minted by
  fanout, no draft of their own).
- Code delivery tier (1): `code` (generator: `git_commit`).
- Plus the supporting tiers `policy`, `vocab`, and `ref` —
  each bundle-declared, each with the lifecycle the platform
  spec specifies.

**Edge instances (5):** `fulfills`, `dependency`, `domain_parent`,
`decomposition`, `policy_application`. All typed against the
platform's 5 edge types (fanout, reference, dependency,
policy_application, synthesis).

**Fragment kinds (5):** `techspec`, `pubapi`, `privapi`,
`policies`, `failure_surface`.

**Structural rules:** foundation component at every structural
level, two-level component depth cap, unified
domain/presentational DAG with fan-in synthesis for fanned-out
domain components.

**Cold-start order (scaffolding):**
input → feature_expansion → requirements → sysarch →
comparch → subcomparch → impl → fanin → code.

**Flows (6):** feature-request, refactor, bug-fix-propagation,
downward-propagation, upward-propagation, plan-change.
Scaffolding is the bundle's baseline behavior with no flow
active, not a flow.

**Phased tiers:** impl, fanin, code. Per-tier scope keys
include `phase` for these; bundle's plan rule (§9) computes
phase assignment.

---

## 1. Tier vocabulary

One subsection per tier. Each pins the tier's scope, identity,
handle, body grammar (where applicable), and generator.

### 1.1 `feature_expansion`

Project-level extraction tier. Reads the project's
`project_doc` input document; produces a structured
`<features>` body listing each feature the project must
deliver, with a one-paragraph `<intent>` per feature plus
optional `<vocabulary>` sections defining project terms.

- **Scope:** `singleton` (one per project, `comp_id="proj"`).
- **Identity:** `id`.
- **Handle:** the full features list, each feature's intent
  prose, the project's vocabulary.
- **Body grammar:** root `<features>` with one or more
  `<feature>` children and optional `<vocabulary>` block.
- **Generator:** `llm`.
- **Review:** yes.
- **Phased:** no.

Approving feature_expansion mints `vocab_*` entries from the
`<vocabulary>` block. Features themselves are not minted as
separate tier nodes — they live as structured fields on
feature_expansion's body and are referenced downstream by
position or by name.

### 1.2 `requirements`

Project-level rotation tier. Reads feature_expansion's handle;
produces a structured `<requirements>` body listing
system-level `<responsibility>` entries that collectively
fulfill the feature set. Each `<responsibility>` carries a
name, a prose summary, and a `<feats>` block listing which
feature ids it implicates.

- **Scope:** `singleton`.
- **Identity:** `id`.
- **Handle:** the full responsibilities list with their
  feature-implication references.
- **Body grammar:** root `<requirements>` with one or more
  `<responsibility>` children.
- **Generator:** `llm`.
- **Review:** yes.
- **Phased:** no.

The features→responsibilities axis rotation is the chain's
first compression: many features map to fewer responsibilities;
features are user-facing while responsibilities are
system-level. The chain only descends from responsibilities
downward.

### 1.3 `sysarch`

Project-level compression tier. Reads requirements' handle;
produces a system architecture body listing top-level
components, their dependencies, their domain-parent
relationships (for presentational components), and
project-level policies.

- **Scope:** `singleton`.
- **Identity:** `id`.
- **Handle:** the components list, project-level techspec,
  project-level policies, dependency edges, domain-parent
  edges.
- **Body grammar:** markdown sections (`## project_techspec`,
  `## project_policies`, `## project_dependencies`,
  `## project_domain_parents`) plus structured
  `<components>`, `<policies>`, `<dependencies>`,
  `<domain-parent>` XML blocks.
- **Generator:** `llm`.
- **Review:** yes.
- **Phased:** no.

Approval mints `comp_*` nodes via fanout, `policy_*` nodes
from the `<policies>` block, `dependency` edges among comps,
and `domain_parent` edges from presentational comps to their
domain parents.

### 1.4 `comp` — join target

A top-level component minted by sysarch's fanout. No body of
its own; content is written by the comparch tier via
`produces:` declarations onto the comp's fragments.

- **Scope:** `child_of(sysarch)` (minted by fanout).
- **Identity:** `id`.
- **Kind attribute:** `domain` or `presentational`. Set at
  mint time from the sysarch declaration.
- **Foundation attribute:** boolean. Set at mint time from
  the sysarch `<foundation/>` marker.
- **Handle:** `name`, `kind`, `is_foundation`, plus the
  fragments written by comparch (techspec, pubapi, privapi,
  policies, failure_surface).
- **Body:** none — join target.
- **Generator:** none.

The comp tier exists so other tiers can target it via edge
endpoints. Its content lives entirely in its fragments.

### 1.5 `comparch`

Per-component compression tier. Reads the comp's handle, the
fulfilled responsibility handles, dependencies' pubapi
fragments, and (for presentational comps) domain parents'
synthesis handles. Produces the comp's techspec, public API,
private API, policies, failure surface, and a subcomponent
decomposition.

- **Scope:** `per(comp)`.
- **Identity:** `id`.
- **Handle:** decomposition summary (subcomponent list and
  ownership structure). Other readers reach comparch's
  outputs via the comp's handle (since comparch writes
  fragments onto the parent comp).
- **Body grammar:** markdown sections (`## comparch:techspec`,
  `## comparch:pubapi`, `## comparch:privapi`,
  `## comparch:policies`, `## comparch:failure_surface`) plus
  structured `<subcomponents>` (each with per-subcomponent
  `<owns>` claims on parent responsibilities + feature
  slices) and `<sub-dependencies>` XML blocks.
- **Generator:** `llm`. Comparch runs at `thinking_effort:
  max` because it carries the in-prompt reconciliation pass.
- **Review:** yes.
- **Phased:** no.
- **`produces:`** — techspec, pubapi, privapi, policies,
  failure_surface fragments on `self.parent` (the comp).

Approval mints `subcomp_*` nodes via fanout, subcomp-to-subcomp
`dependency` edges from `<sub-dependencies>`, and
per-subcomponent `<owns>` claims that materialize as
`fulfills` edges from each subcomp to the parent comp's
responsibilities (sliced by feature where the body declares
slice ownership).

### 1.6 `subcomp` — join target

A subcomponent minted by comparch's fanout. Same shape as
`comp` but one level deeper. Content lives in fragments
written by subcomparch.

- **Scope:** `child_of(comparch)`.
- **Identity:** `id`.
- **Handle:** `name`, fragments written by subcomparch.
- **Body:** none.
- **Generator:** none.

### 1.7 `subcomparch`

Per-subcomponent leaf articulation tier. Reads the subcomp's
handle, its parent comp's handle, the parent comp's
non-subcomponent fragments (techspec, pubapi, privapi,
policies, failure_surface), and cross-subcomp dependencies'
pubapi fragments. Produces typed API signatures, internal
design, policies (if any), and failure surface for the
subcomponent.

- **Scope:** `per(subcomp)`.
- **Identity:** `id`.
- **Handle:** decomposition-style summary, fragments produced
  on the parent subcomp.
- **Body grammar:** markdown sections (`## subcomparch:techspec`,
  `## subcomparch:pubapi`, `## subcomparch:privapi`,
  `## subcomparch:policies`, `## subcomparch:failure_surface`)
  plus typed signatures in XML.
- **Generator:** `llm`.
- **Review:** yes.
- **Phased:** no.
- **`produces:`** — techspec, pubapi, privapi, policies,
  failure_surface fragments on `self.parent` (the subcomp).

No further decomposition — subcomparch is the leaf
articulation tier. Below it the chain transitions from design
to implementation.

### 1.8 `impl`

Implementation design tier. **Phased.** One body per
`(subcomp, phase)` pair. Reads the subcomp's handle, the
parent comp's handle, project-wide sysarch sections,
related features (sliced by what the subcomp's `<owns>`
block claims), and for phases > 1 the prior-phases'
impl handles for the same subcomp.

- **Scope:** `per(subcomp) × phase`.
- **Identity:** `id`.
- **Handle:** structured description of the implementation
  approach for this phase.
- **Body grammar:** markdown sections (implementation
  overview, data models, interfaces, error handling, testing
  approach) plus structured `<types>`, `<functions>`, and
  `<tests>` XML blocks.
- **Generator:** `llm`.
- **Review:** yes.
- **Phased:** yes.

For an un-fanned-out top-level component (one without
subcomponents), impl scopes directly under the comp instead:
`per(comp where count(subcomponents) == 0) × phase`. The bundle
uses a named predicate to cover both cases.

Impl is the bridge between design (comparch/subcomparch) and
code (the `code` tier). Impl prose is detailed enough that a
coding agent reading it produces correct code without further
design decisions.

### 1.9 `fanin`

Domain fan-in synthesis tier. **Phased**, **`generator:
synthesis`**. Aggregates the as-built handles of a domain
component's subcomponents at a given phase; produces a
component-level summary that presentational consumers of the
domain read.

- **Scope:** `per(comp where kind == domain AND
  count(subcomponents) > 0) × phase`.
- **Identity:** `id`.
- **Handle:** aggregated synthesis content (combined pubapi
  surface, observed dependency patterns, structural caveats).
- **Body grammar:** markdown sections aggregating subcomp
  pubapis with structural notes about what the domain
  exposes at this phase.
- **Generator:** `synthesis` — the platform aggregates
  child handles per the bundle's synthesis-walk declaration.
- **Review:** yes.
- **Phased:** yes.

A presentational comp's comparch reads its domain parents'
fanin handles as context — this is how the chain handles
"presentational depends on as-built domain" without forcing
top-down design of the presentational surface upfront.

### 1.10 `code`

Code delivery tier. **Phased**, **`generator: git_commit`**.
Reads the impl handle; pulls actual source code from a
sibling code repository at a committed sha.

- **Scope:** `per(impl) × phase` (mirrors impl's phase
  dimension).
- **Identity:** `id`.
- **Handle:** the file paths + content of the source the impl
  produced for this phase.
- **Body grammar:** none — content is a git blob from the
  code repo.
- **Generator:** `git_commit`. The bundle declares the code
  repo URL and a path-from-handle expression.
- **Review:** no (code review happens in the code repo's own
  review process).
- **Phased:** yes.

The code tier exists so the chain's terminal output — actual
source files — has a first-class place in the structured
model. Downstream tiers (none in the default bundle) could
reference code handles, but typically nothing reads them.

### 1.11 `policy`

Cross-cutting constraint nodes minted by `<policies>` blocks
in sysarch and comparch bodies. Each policy has a trigger
phrase, a required-action description, an applies-to scope,
and a rationale.

- **Scope:** `child_of(sysarch)` (project-level) or
  `child_of(comparch)` (component-local).
- **Identity:** `id`.
- **Handle:** trigger phrase, required action, rationale,
  outgoing `policy_application` edges to the comps or
  subcomps the policy applies to.
- **Body:** none — minted from the `<policies>` fragment of
  the parent arch doc.
- **Generator:** none.

Policies are the bundle's mechanism for cross-cutting
invariants — "every privileged action lands in the audit
log," "every persisted secret is encrypted at rest." Their
application edges propagate the policy's required action
through the reachability graph; downstream tiers see "this
policy applies to me" as part of their context.

### 1.12 `vocab`

Project glossary terms. Minted by feature_expansion's
`<vocabulary>` block (project-level) or by
feature-specific vocabulary declarations (feature-local).

- **Scope:** `singleton` (project-level vocab pool) or
  `per(feature_id)` (feature-local terms).
- **Identity:** `id`.
- **Handle:** term name, definition, disambiguation, see-also
  references.
- **Body grammar:** `<vocab-entry>` root with `<name>`,
  `<definition>`, `<disambiguation>`, optional
  `<see-also target="..."/>` cross-references.
- **Generator:** `llm` for initial mint and edits; agent can
  also author directly via the `add_vocab_entry` write tool.
- **Review:** yes (advisory).
- **Phased:** no.

Project vocabulary is what makes prose handles in downstream
tiers stay consistent across the chain. Without it, the LLM
re-coins terms at every tier.

### 1.13 `ref`

Free-form supplemental content nodes. Created via the agent's
`create_reference` write tool or via the dashboard's
References page. Used for content that doesn't fit any of the
chain tiers but downstream tiers need to reference — DSL
specs, deployment runbooks, design memos, implementation
guides.

- **Scope:** `singleton` (one ref pool per project; instances
  have no parent).
- **Identity:** `id`.
- **Handle:** title, body, outgoing `<see-also>` references.
- **Body grammar:** `<reference>` root with `<title>`,
  `<body>`, optional repeated `<see-also target="..."/>`.
- **Generator:** `llm` for content-from-seed expansion when
  the agent supplies only a seed description; direct content
  storage when the agent supplies full body content.
- **Review:** yes.
- **Phased:** no.

**Default-bundle convention: refs are implementation detail.**
The default bundle wires refs into comparch and below — they
hold the kind of supplemental content (DSL specs, runbooks,
implementation guides) that affects how components and
subcomponents implement their architecture. Sysarch and above
don't consume refs because their decisions are architectural,
not implementation-detail. This is a bundle decision; another
bundle could wire refs higher or lower depending on what
content it expects refs to carry.

---

## 2. Edge vocabulary

Five named edge instances, each typed against one of the
platform's five edge types. The bundle declares the specific
source/target tiers, cardinality, and graph constraints; the
platform handles the type-level semantics.

### 2.1 `fulfills`

Typed as platform `reference`. Comp → resp pointer expressing
"this component fulfills this responsibility."

- **Source:** `comp`. **Target:** responsibility (as a field on
  requirements; see §2.5 on how the bundle handles
  responsibilities-as-fields).
- **Declared in:**
  `sysarch.draft.components[].responsibilities[].@id`.
- **Cardinality:** source `min: 1` (every comp fulfills at
  least one resp); target `min: 1, max: 1` (every resp is
  fulfilled by exactly one comp).

The fulfills edge is what makes the chain's many-to-one
"responsibilities collapse into components" assignment
queryable. Comparch reads its comp's fulfilled responsibilities
via this edge.

### 2.2 `dependency`

Typed as platform `dependency`. Both comp→comp (top-level
deps) and subcomp→subcomp (within a parent's fanout). Always
acyclic.

- **Source:** `comp` or `subcomp`. **Target:** same tier.
- **Declared in:**
  `sysarch.draft.components[].dependencies[].@to` (top-level),
  `comparch.draft.sub_dependencies[]` (within-comp subcomp deps).
- **Cardinality:** unbounded.
- **Graph constraint:** `acyclic`, `no_self_loop`.
- **Scope:** top-level deps project-wide; subcomp deps scoped
  to `within(comparch)` — both endpoints must live in the
  same parent's fanout.

The dependency edge is the chain's primary structural
dependency. A dependent reads its dependencies' pubapi
fragments in its context walks.

### 2.3 `domain_parent`

Typed as platform `reference`. Presentational comp → domain
comp pointer indicating "this presentational surface mirrors
this domain."

- **Source:** `comp` where `kind == presentational`.
  **Target:** `comp` where `kind == domain`.
- **Declared in:**
  `sysarch.draft.domain_parent[].parent[].@to`.
- **Cardinality:** unbounded; a presentational comp can mirror
  multiple domain parents.

The domain_parent edge is what enables presentational
comparch to read fan-in synthesis of its domain parents
without forcing presentational design upstream.

### 2.4 `decomposition`

Typed as platform `fanout`. Used in three places:

- Sysarch → comp: top-level components minted by sysarch's
  fanout.
- Comparch → subcomp: subcomponents minted by comparch's
  fanout.
- Feature_expansion → vocab: vocabulary terms minted by the
  feature_expansion body's `<vocabulary>` block.

Each instance is declared per-tier in the bundle; the
mechanism is the same.

### 2.5 `policy_application`

Typed as platform `policy_application`. Policy node → comp
(or subcomp) target.

- **Source:** `policy`. **Target:** `comp` or `subcomp`.
- **Declared in:**
  `sysarch.draft.policies[].applies_to[]` for project-level
  policies; `comparch.draft.policies[].applies_to[]` for
  component-local policies.
- **Cardinality:** target unbounded (a policy can apply to
  many targets); source unbounded (a target can have many
  applied policies).
- **Reachability:** transitive — a policy applied to a comp
  reaches every subcomp under it unless an intervening
  policy declaration overrides.

The policy_application edge is what makes cross-cutting
invariants queryable from each consuming tier — comparch sees
"these policies apply to me," and its prompt incorporates
them into the architecture decisions.

### A note on responsibilities

Responsibilities are not a separate tier in v4 (unlike v3
which had `resp`). They live as structured fields on the
requirements body. Edges that reference them (`fulfills`,
ownership claims in comparch's `<owns>` blocks) resolve by
the responsibility id as declared in requirements' body. The
platform tracks responsibilities as a projection
(`responsibilities`) derived from the requirements body for
query efficiency, but the tier-set lists no `resp` entry.

This is a v4 simplification. v3's separate resp tier added
complexity (sub-responsibilities under each comp via the
`subreqs` tier) that v4 collapses into comparch's per-subcomp
`<owns>` blocks.

---

## 3. Fragments and transclusion

Fragments are authored sub-blocks of content owned by a node
but written by a different tier. The default bundle declares
five fragment kinds; each kind has a specific owner tier and
authoring tier.

### 3.1 Fragment kinds

- **`techspec`** — technical specification: runtime,
  persistence, write-path, concurrency, testing, deploy,
  technologies. Owned by `comp` (project-wide; written by
  sysarch's `## project_techspec` section). Owned by
  `subcomp` (component-level; written by comparch via
  `produces:` from its `## comparch:techspec` section).
- **`pubapi`** — public API surface. Owned by `comp` (written
  by comparch from `## comparch:pubapi`). Owned by `subcomp`
  (written by subcomparch from `## subcomparch:pubapi`).
- **`privapi`** — private API surface. Owned by `comp`
  (written by comparch). Owned by `subcomp` (written by
  subcomparch).
- **`policies`** — applied policies as prose. Owned by `comp`
  (written by sysarch for project-level; written by comparch
  for component-local). Owned by `subcomp` (written by
  subcomparch for subcomponent-local).
- **`failure_surface`** — failure mode catalogue. Owned by
  `comp` (written by comparch). Owned by `subcomp` (written
  by subcomparch).

### 3.2 The `produces:` mechanism

A tier writes fragments on another node via the `produces:`
declaration in its tier definition. For example, comparch
produces fragments on its parent comp:

```yaml
comparch:
  produces:
    - fragment: { owner: self.parent, kind: techspec,
                  authored: draft.techspec }
    - fragment: { owner: self.parent, kind: pubapi,
                  authored: draft.pubapi }
    # ...
```

The `authored:` path tells the reducer which body section
the fragment's content comes from. When comparch's draft
commits, the reducer reads each declared section and writes
it as a fragment row on the parent comp.

### 3.3 Authored-only

Fragments are authored-only. There is no derived-fragment
category where the reducer computes a fragment's content
from other state. Every graph-derived view a prompt needs
is expressible as a context-walk expression evaluated at
read time.

### 3.4 Fragment as the unit of regeneration

When a tier regenerates (because upstream context changed,
a flow asked, or the user fed back feedback), the generator's
output is a fragment-scoped delta — only the fragments the
new draft actually changes get new content; untouched
fragments stay at their prior values. This makes propagation
cheap and provenance clean (each fragment carries a single
driver record on the regen that wrote it).

---

## 4. Structural rules

The default bundle enforces five structural invariants on the
component graph. Each is implemented as a bundle-declared
cardinality, graph constraint, or named predicate; together
they shape the kind of architecture the chain produces.

### 4.1 Foundation at every level

Every project must have at least one foundation top-level
component. Every comparch must declare at least one
foundation subcomponent. Foundation components carry
cross-cutting infrastructure (data persistence, logging,
error reporting) other components depend on.

Implementation: a named predicate `has_foundation_child` plus
cardinality on the comp tier and the subcomp tier:

```yaml
predicates:
  has_foundation_child:
    count(decomposed_by(child) where child.is_foundation == true) >= 1

# applied to sysarch and comparch
cardinality.when: has_foundation_child
```

### 4.2 Two-level depth cap

Components decompose at most two levels deep:
sysarch → comp → subcomp. No sub-subcomponents. The bundle
declares no decomposition edge from subcomp to a third level.

The depth cap is a meaning-engine choice: at three levels of
component decomposition, the prompts start losing their
target-reader framing because the chain has fragmented the
project into too many small surfaces.

### 4.3 Domain / presentational split

Components carry a `kind` field set to `domain` or
`presentational`. The split is enforced at sysarch mint time
from the declared kind in `<components>` blocks.

Domain components implement responsibility-bearing
back-of-the-system surfaces. Presentational components
implement user-facing surfaces that consume one or more
domain components.

A `domain_parent` edge (§2.3) from a presentational comp
to its domain parents wires the presentational comp into
the fan-in synthesis flow.

### 4.4 Fan-in synthesis

Every domain component with subcomponents gets a `fanin`
node that aggregates the subcomponents' as-built handles.
Presentational comparch reads its domain parents' fanin
handles as context.

The fanin tier is `generator: synthesis` (§1.9) — the
platform handles the first-pass readiness gate (synthesis
fires when all required-content children are approved) and
the staling-on-child-change behavior.

### 4.5 Acyclic dependency graph

All `dependency` edges enforce `acyclic`, `no_self_loop`.
Within-comp subcomp dependencies enforce the same
constraints scoped to the parent's fanout.

The acyclicity invariant is what lets the readiness query
terminate — a dependent can read its dependency's pubapi
fragment because the dependency is upstream in the chain.
Cycles would break this and prevent any node in the cycle
from ever being ready.

---

## 5. Policies

Policies are cross-cutting constraints the bundle minted as
`policy_*` nodes. Each policy has a trigger phrase
describing when the policy applies, a required action
describing what must happen, an applies-to list of comp or
subcomp ids, and a rationale.

### 5.1 Project-level vs component-local

Sysarch's `<policies>` block mints project-level policies.
These apply across multiple components — anything the bundle
flags as cross-cutting before component decomposition.

Comparch's `<policies>` block mints component-local
policies. These apply only within the component scope and
reach subcomponents underneath via reachability.

### 5.2 Policy application

Each policy has `policy_application` edges to its
applies-to targets (§2.5). Targets see "this policy
applies to me" in their context walk — comparch sees
applied project-level policies in its
`context.applied_policies` variable; subcomparch sees the
union of applied project-level and component-local
policies.

### 5.3 Policies in the generator prompt

Per-tier Liquid templates incorporate applied policies into
their prompt as a structured section. The reviewer's
context walk reads the same policies; the reviewer's
"architectural-decisions" findings flag drift if the
generated body violates an applied policy.

---

## 6. Project vocabulary

The vocab tier carries terms the project uses with specific
meaning that downstream tiers need to use consistently. Vocab
entries arrive in two ways:

- **Bundle-shipped**: none by default.
- **Author-extracted**: feature_expansion's `<vocabulary>`
  block, vocab entries minted at approval.
- **Author-added**: the agent's `add_vocab_entry` write tool
  during scaffolding or via the dashboard.

Each entry has a name, a definition, a disambiguation note
when the term might collide with common usage, and optional
see-also references to related vocab.

The vocab tier participates in context walks: every
generation prompt receives a `{{ vocab }}` Liquid variable
with the relevant terms — typically the project-level vocab
plus any feature-local vocab for the features the current
scope owns. The bundle declares this walk per tier.

Approving a regenerated feature_expansion can mint new
vocab; the platform's staling machinery propagates the new
terms to downstream tiers, which see fresh vocab on their
next regen.

---

## 7. How this bundle uses refs

Refs are the bundle's escape hatch for content that doesn't
fit any chain tier — supplemental material the chain needs
to reference but didn't generate.

### 7.1 What goes in a ref

Typical ref content:

- DSL specifications a generator tier needs to know about.
- Deployment runbooks describing operational procedures.
- Design rationale memos pinning down subtle invariants.
- Implementation guides for specific technologies.
- Partial spec copies from upstream projects.

What does NOT go in a ref:

- Feature decompositions (use feature_expansion's body).
- Responsibility lists (use requirements' body).
- Component architecture (use sysarch / comparch / etc.).

The principle: refs hold *implementation detail* — material
that affects how the chain implements its decisions, not
what the decisions are. Architectural decisions belong in
the chain tiers; implementation guidance belongs in refs.

### 7.2 Wiring refs into context

The default bundle's comparch, subcomparch, and impl tiers
declare reference context walks:

```yaml
comparch:
  context:
    # ... structural walks ...
    - self.reference → ref.handle    # any attached refs
```

The `self.reference` walk follows reference edges from the
current node to any attached refs and yields each ref's
handle as a Liquid variable. The prompt template reads
`{{ refs }}` and incorporates each ref's content.

The default bundle does NOT wire refs into feature_expansion,
requirements, or sysarch — refs are implementation detail,
those tiers handle architectural decisions, the separation
prevents implementation noise from leaking into design.

### 7.3 Attaching refs

The agent attaches a ref to a node via the
`attach_reference(project_id, source_node_id, ref_id)`
write tool. The platform handles the body edit (inserting a
`<reference target="ref_id"/>` block in the right
structural location) and the edge derivation.

Refs can also be attached via the dashboard's per-node
detail view. Attachment fires staleness on the consuming
node — its next regen sees the newly available ref content.

### 7.4 Ref grammar and lifecycle

Refs have the same draft → review → approve lifecycle as
any other tier. The ref's body is the structured
`<reference>` block with title, body, and see-also
cross-references; the LLM expands a seed description into
the full structured form on initial create, and revisions
flow through the standard feedback-regen path.

---

## 8. Generation plan

The bundle ships scaffolding as its baseline behavior plus
six flows for non-scaffolding work shapes.

### 8.1 Scaffolding (baseline)

Scaffolding is what runs when no flow is active: the chain
walks from input doc through every reviewed tier in
dependency order. The agent's `/scaffold` skill drives this
by repeatedly querying `list_ready_scopes` and drafting
each ready scope until the chain has populated end-to-end.

Scaffolding order:

1. `feature_expansion` (singleton).
2. `requirements` (singleton).
3. `sysarch` (singleton).
4. `comparch` (per top-level comp).
5. `subcomparch` (per subcomp).
6. `impl` (per subcomp per phase, in phase order).
7. `fanin` (per domain comp per phase, in phase order).
8. `code` (per impl per phase, by external commit).

Steps 4 and 5 process foundation components first (per the
foundation invariant in §4.1). Within step 4, comparch
processes comps with no incoming dependencies first, then
their dependents (per the acyclic dependency invariant).

Scaffolding is not a flow — no schema delta, no walk
primitive, no flow.yaml. It's just the base schema running
with the agent picking from `list_ready_scopes`.

### 8.2 Flows

Six flows ship in `bundles/default/flows/<name>/`. Each
flow is declared as a schema delta plus prompt files. The
platform spec's §A.5 covers flow mechanics generally; this
section pins the default bundle's specific choices.

#### `feature_request`

User describes a desired feature change in prose.
Walk: `downward_cascade`. Adds a `feature_request_plan`
planning tier per scaffold tier the cascade visits.

Used to add a feature to an already-scaffolded project:
the cascade walks from feature_expansion down through every
tier the new feature implicates, regenerating each in the
new state.

#### `refactor`

User describes a structural change to existing functionality
(component reshape, dependency reroute, responsibility
redistribution). Walk: `downward_cascade`. Adds a
`refactor_plan` planning tier.

Differs from `feature_request` in scope: refactor doesn't
add new functionality; it reshapes how existing
functionality is delivered. The plan grammar enforces this
discipline.

#### `bug_fix`

User describes a defect — incorrect behavior at a specific
scope. Walk: `downward_cascade`. Adds a `bug_fix_plan`
planning tier.

Used to fix observed problems without disturbing the
architecture. The flow visits the originating tier plus
downstream tiers that need regeneration.

#### `downward_propagation`

Explicit version of what staling does implicitly. User
re-approves an upstream scope; the flow opens to drive
explicit per-scope plans for downstream regeneration. Walk:
`downward_cascade`. Adds a `propagation_plan` planning tier.

Used when an upstream change requires explicit attention at
each downstream scope rather than implicit accumulation of
staleness markers.

#### `upward_propagation`

A downstream argument suggests an upstream decision was
wrong: a comparch flags its responsibilities as infeasible,
a subcomparch flags its parent's API surface as
under-specified. Walk: `up_then_down`. Adds an
`assessment_plan` planning tier at the affected upstream
scope and a downstream `propagation_plan` after the upstream
re-approves.

Used when downstream work surfaces an upstream design
problem that needs to be fixed before downstream work can
continue.

#### `plan_change`

User changes a phase plan (moves features between phases,
splits a phase, drops a phase). Walk: `downward_cascade`
over the affected `(subcomp, phase)` and `(comp, phase)`
pairs. Regenerates phased impl + fanin + code bodies whose
phase assignments changed.

Used when delivery phasing changes. The plan recompute
itself happens in the reducer (§9.4); the flow handles the
resulting regeneration cascade.

---

## 9. The phase plan

The bundle declares which tiers are phased and the rule that
computes phase assignment.

### 9.1 Phased tiers

`impl`, `fanin`, `code`. Scope keys carry a `phase`
dimension; bodies live at `<tier>/<scope_path>/p<phase>/body.md`.

### 9.2 The plan rule

The bundle's plan rule lives at `bundles/default/plan.yaml`
and computes phase assignment in four steps:

1. **User-pinned feature phases.** The user pins each
   approved feature to a phase via the dashboard. The
   default is phase 1.
2. **Cascade up the chain.** Each responsibility is
   assigned to the earliest phase any implicating feature
   is in. Each component to the earliest phase any
   fulfilled responsibility is in. Each subcomponent to
   the earliest phase the parent component is in. Each
   impl to its subcomponent's phase.
3. **Foundation overrides.** Foundation components and
   their downstream impls are assigned to phase 1
   regardless of their fulfilled responsibilities' phases.
   Other components depend on foundation; foundation must
   build first.
4. **Dependency ordering.** A component depending on
   another component cannot be in an earlier phase. The
   plan rule rejects invalid assignments with a typed
   error.

### 9.3 Cross-phase context

Phased impl prompts receive a `prior_phases` Liquid
variable carrying the as-of-prior-phase impl handles for
the same subcomponent. The bundle's impl context walk:

```yaml
impl:
  scope: per(subcomp) × phase
  context:
    # ... standard subcomp/comp/sysarch walks ...
    - self.prior_phases → target.handle
```

The prompt incorporates the delta: "this impl is for phase
N; phases 1..N-1 produced these handles; build the next
slice that's consistent with them."

### 9.4 Plan recomputation

The plan recomputes whenever a body affecting assignment
changes — sysarch regenerated (component set changed),
comparch regenerated (subcomponent set changed), user
re-pinned a feature phase. The recompute runs as part of
the reducer branch for the triggering event; the new plan
is written to the `phase_plan` projection in the same
transaction.

Phase changes mark affected phased-tier scopes stale; the
agent sees them in `list_ready_scopes` and may regenerate
them at the user's direction, or open a `plan_change` flow
to drive the regeneration explicitly.

---

## 10. Thinking effort

The bundle declares per-tier `thinking_effort` for tiers
where deep reasoning improves output quality.

- **`feature_expansion`, `requirements`, `sysarch`**: max.
  The extraction + rotation + compression at the top of the
  chain benefits from deep reasoning because handle quality
  here determines downstream quality.
- **`comparch`**: max. The in-prompt reconciliation pass
  (cross-section consistency, surface closure, dependency
  grounding, single-owner discipline) is the most demanding
  generation in the chain.
- **`subcomparch`, `impl`, `fanin`, review tiers**:
  default. Late-stage compression doesn't need deep
  reasoning — the handles are already compressed by the
  time they arrive at these tiers.

The bundle declaration tells the agent which budget to
assign per tier; the platform doesn't enforce thinking
effort, it just exposes the bundle's recommendation through
the MCP read tools.
