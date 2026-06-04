# Catapult — Specification (v4)

**Status:** in-progress prose draft. v4 supersedes v3's TOC draft.

The spec is structured as three parts. **Part A** describes the
platform — the abstract reactive-graph runtime that every
Catapult deployment runs, plus the small vocabulary of edge
types, generators, and roles the platform recognizes. **Part B**
describes the default bundle — the specific tier graph,
prompts, grammars, and flow definitions that ship as
`bundles/default/` in a fresh project and produce architectural
artifacts for AI code generation. **Part C** describes the
implementation architecture — Elixir/OTP, Postgres, Commanded,
Phoenix/LiveView, the remote MCP server, the local Go CLI.

The line between Part A and Part B is the configurability lever.
A different bundle could replace every concrete decision in
Part B without touching anything in Part A: a domain-specific
language for music composition, a structured editor for legal
contracts, a graph-of-prompts pipeline for generating training
curricula — any work shape that can be expressed as a chain
of structured artifacts produced through a reviewable pipeline
can ship as a bundle and run on the same platform. The default
bundle is one worked example of the platform contract.

---

# Part A — Platform

## A.0 Vision

Catapult is a **design memory** system. Knowledge work happens
once, in scattered conversations across documents, comment
threads, meeting notes, and tribal knowledge that leaves with
the people who hold it. Catapult is the machine that catches
that work as it happens, structures it into a traversable graph
of artifacts, and keeps the *why* attached to every decision so
the system as a whole remains explicable to humans and to
agents long after the original author has moved on.

The artifacts Catapult produces are structured input for
downstream AI work. The default bundle produces software design
artifacts — feature expansions, requirements, component
architectures, implementation specs — that an AI coding agent
reads to write code without inventing contracts the human
author had in mind but never wrote down. Other bundles produce
other artifact graphs for other ends. What's common is the
shape: a tiered chain of structured documents, each tier
producing compressed handles the next tier reasons from,
reviewed at each step, committed to a git repository.

The user works through Claude Code. Catapult is the substrate
Claude Code reads, writes, and reasons about. There is no
separate Catapult interface for *generation* — there is a
dashboard for *observation* (the structured graph, the review
queue, the phase plan), but the working interface is a CC
session in front of a project repository.

### A.0.1 The load-bearing architectural commitments

Four commitments shape every later chapter and explain what
Catapult does and doesn't do:

1. **Claude Code is the driver.** The user opens a CC session
   and works through skills + slash commands that read state,
   compose artifacts, commit them, and advance the chain. There
   is no server-side workflow engine that "runs" a project.
   Catapult does not call LLMs; CC does.
2. **The server is pure state.** Catapult's job is to hold the
   event log, derive projections from a bundle-declared schema,
   enforce invariants at command time, and serve "what's ready
   next" to the agent. It reacts to commits the agent makes.
   It does not initiate work, does not poll for things to do,
   does not run background generation, does not orchestrate
   flows. Workflow lives in the agent's skill suite, not in
   the server.
3. **State lives in Postgres; artifacts live in git.** The body
   files a generator produces (the structured content tiers
   carry) live in the user's project git repo and are pushed
   to a git remote Catapult can fetch from. Reviews live
   alongside their bodies in git so iterations are diffable.
   Everything else — status, draft history, approvals, edges,
   propagation records, the phase plan, the event log itself —
   lives in Catapult's Postgres. The split is clean because
   bodies and reviews are the only things humans want to
   `git diff` across iterations, and state is the only thing
   the system needs to query.
4. **Single user has write access; collaborators have read.**
   The project owner drives. Collaborators can log in to the
   dashboard, see the structured graph, read reviews, and pull
   the project repo locally — but they cannot drive the chain.
   This is a deliberate scope choice, not a deferred extension:
   the system is designed around one driver per project, and
   multi-user concurrent write would require a different
   coordination model than the agent-driven-state-machine
   pattern the rest of the spec builds on.

These four commitments rule out a substantial set of features a
collaborative design-memory product would carry — multi-reviewer
assignment, scoped roles, governance dashboards, server-side
workflow engines, AI sandboxing for code execution, complex
credential management. Those aren't in this spec. The spec
describes Catapult as it is.

### A.0.2 The self-bootstrapping invariant

Catapult is built by reading this specification through
**SiegeEngine**, the predecessor system. SiegeEngine walks an
input document through a tier chain, drafts and reviews each
artifact, and commits the resulting bodies to a git repository.
Pointed at this spec, SiegeEngine produces the body files for
Catapult's own architecture — feature expansions, requirements,
sysarch components, comparch decompositions, all the way down
to implementation artifacts a coding agent reads to write the
code.

The artifacts SiegeEngine produces in that bootstrap pass must
be **byte-identical** to what Catapult, once running with the
default bundle, would produce for the same input. The reason
this matters: it's the test that the specification is honest.
If Catapult's spec says "the chain produces these artifacts
via this prompt sequence" and SiegeEngine produces something
different running the same prompts on the same input, the spec
is wrong somewhere — the prompts diverge, the readiness rules
diverge, the grammar diverges. The byte-identity check forces
the spec to be self-contained: it cannot reference SiegeEngine's
internals to explain Catapult's behavior, because SiegeEngine
doesn't know about itself when it's reading the spec as an
input document.

Once SiegeEngine has produced Catapult's body files, a fresh
Catapult instance ingests them: fetches the project branch,
walks the body tree, materializes the equivalent state in
Postgres, and is then the running system. Subsequent design
iteration happens through Catapult.

---

## A.1 The structured model

Catapult organizes work into a graph of **nodes** of distinct
**tiers**, connected by typed **edges**, producing **bodies**
(and optionally **reviews**) committed to git. Tiers expose
**handles** — a public surface other tiers read — and may
**produce fragments** stored on other nodes. Generators turn
the readable handles of upstream nodes into a tier's own body
content.

This chapter introduces the vocabulary at platform level. The
specific tiers a project uses, the shape of their scopes, the
grammar of their bodies, the readiness rules that gate
generation — all of that is bundle content, declared in
`bundles/<name>/`. Chapter A.2 (the bundle abstraction)
specifies the bundle declaration mechanics in full. This
chapter just names the concepts the bundle uses.

### A.1.1 Tiers

A **tier** is a kind of node in the generation graph. Each
tier represents one layer of structured work in the chain;
each node of that tier is one artifact at that layer. Tiers
are bundle-declared — the bundle for a software-design pipeline
declares tiers for features, requirements, components, and
implementations; a DSL-authoring bundle might declare tiers
for syntactic constructs, semantic rules, and example
programs; a music-composition bundle might declare tiers for
themes, harmonic skeletons, and per-instrument parts. The
platform makes no assumption about what tiers represent — it
runs whatever graph the bundle declares.

Tiers can have generators (their content gets produced — by an
LLM, by a git commit, by a synthesis aggregation, or by other
generator types Part B catalogs). Tiers can also exist as pure
join targets — present in the graph so edges can terminate on
them, but with no content of their own. The bundle declares
each tier's generator (or absence of one).

### A.1.2 Scopes

Every node of a tier has a **scope** — a stable identity within
its tier that the platform uses as the node's primary key.
Scopes are derived from a bundle-declared expression on each
tier: a tier might be a singleton (one node per project), or
`per(parent_tier)` (one node per parent of that tier), or
`child_of(parent_tier)` (minted by the parent's fanout edge),
or something more exotic the bundle's scope expression
captures.

The platform recognizes scope expressions as the mechanism by
which a tier attaches to the graph. It does not enumerate a
fixed set of dimensions — the bundle is free to declare scopes
keyed off whatever upstream structure makes sense for the
domain. A scope's path on disk is derived deterministically
from its key, but the path layout itself is bundle content.

Scope keys, once minted, are persisted as Postgres state.
There are no identity ledger files in git — the only on-disk
content per scope is the body file and (when present) the
review file.

### A.1.3 Bodies

A **body** is the per-scope artifact in git: typically a
markdown file with embedded structured sections that downstream
tiers parse, though the body's grammar is entirely bundle-
declared and a different bundle might use a different file
format. The body is the source of truth for the structured
fields and fragments the platform projects out of it; Postgres
projections are *derived* from body content and are never the
canonical store. Re-projecting from a clean event log + the
bodies at a given git sha produces byte-identical projection
state every time.

The body's grammar is enforced at commit time by the platform's
body validator, which runs the bundle's per-tier grammar
against the submitted body and rejects commits that don't
parse. Validation failure is feedback to the agent, not a
half-committed state.

### A.1.4 Reviews

A **review** is the optional AI-produced critique of a body.
Reviews live in git next to the bodies they review, making
review iterations diffable alongside body iterations. Review
content structure is bundle-declared per tier — a review may
carry a score, structured findings, free-form prose, or any
combination the bundle's grammar specifies.

Reviews are advisory by platform contract. Approving a body
does not gate on the review having completed or having
passed; approval and review are independent lifecycles that
happen to share a draft. A bundle could declare a tier with no
review pass; it could declare a tier whose review carries
mandatory-fix markers the bundle's flow definitions act on.
The platform supports the lifecycle; the bundle decides what
it means.

### A.1.5 Edges and the graph

Tiers are connected by **edges**. The platform recognizes five
edge **types**, each with distinct cardinality, readiness, and
graph-constraint semantics:

- **`fanout`** — parent-creates-children. A parent tier's draft
  property enumerates N children of a child tier; the reducer
  mints the child nodes at parent approval.
- **`reference`** — general-purpose advisory-context edge. A
  named pointer across tiers, resolved via the target's
  identity. Used for any "this node reads that node's handle"
  relationship that isn't a structural dependency.
- **`dependency`** — same-tier or cross-tier data dependency,
  with `acyclic` graph-constraint support enforced by the
  platform via libgraph.
- **`policy_application`** — cross-cutting application of a
  policy-bearing node to a target node, with reachability.
- **`synthesis`** — reverse aggregation. A tier with
  `generator: synthesis` aggregates its children's handles
  and publishes a handle subscribers read via reference-style
  edges.

Bundles declare **named edge instances** typed against one of
these. Each instance specifies its source tier, target tier,
cardinality bounds, and where in the source's draft the edge
gets emitted. The platform owns the edge-type machinery
(cycle detection, cardinality enforcement, fanout reduction,
synthesis aggregation); the bundle owns the named instances
and their endpoints.

The full graph — every edge instance across every tier — must
be acyclic at the type level. The platform validates this at
bundle-load time. Cycles among instances of `dependency` edges
are also forbidden and detected per-instance during projection.

### A.1.6 Handles and fragments

Most generators don't read upstream bodies directly. They read
upstream **handles** — a tier-declared public surface that
combines a named subset of the tier's fields with a named
subset of fragments. Handles are the meaning-engine
abstraction: the bundle author decides what each tier exposes
to its downstream readers, and downstream tiers' context walks
pull handle content, not raw drafts.

A **fragment** is an authored sub-block of content that lives
on a node but may be written by a different tier. The classic
pattern: a parent tier mints a child node with a stub, and a
later tier's draft writes the parent node's `techspec`,
`pubapi`, and `privapi` fragments. The bundle declares fragment
kinds and which tier `produces:` each. The platform tracks
fragment ownership and authorship as part of the projection.

### A.1.7 Generators

A tier's **generator** is the mechanism that produces its body.
The platform recognizes a small set:

- **`llm`** — the default. The tier has a prompt template
  (Liquid, per A.2), a context walk that fills the template's
  variables from upstream handles, and a body grammar the LLM's
  output is validated against. The agent (Claude Code) runs
  the LLM call locally and commits the result.
- **`git_commit`** — the body comes from a git commit on the
  project repo; the platform reads the file at the committed
  path. Used for code-delivery tiers whose content is the
  actual source the project produces.
- **`synthesis`** — the body is computed by aggregating the
  tier's children's handles. Re-runs when any child's relevant
  content changes.
- **`webhook`** — the body comes from an external system
  posting to a Catapult endpoint. The bundle declares the
  payload shape and any authentication requirements.

Bundles may declare additional generator types that the platform
admin has approved for the instance. Most bundles use `llm`
for almost everything and one of the others for narrow
purposes.

### A.1.8 Context walks

A tier's **context** is an ordered list of typed edge-walk
expressions declaring what its generator reads before
producing a body. A walk might say "follow my parent edge,
then walk my parent's fulfills edges to resp nodes, collect
their handles." The context expression is what tells the
platform's scheduler when a `(tier, scope)` pair is ready to
generate — a pair is ready when every traversal in its
context resolves to a content-bearing source.

Context walks are pure functions of the projection. The
reactive engine (§A.3) subscribes to commits, re-runs every
ready tier's context evaluation against the new state, and
writes the resulting ready set into a projection the agent
queries.

### A.1.9 Identity

Each tier declares an **identity strategy** — how downstream
references resolve to nodes of that tier. The platform
recognizes `id` (a minted opaque key), `alias` (a stable
human-meaningful name the bundle specifies — useful when a
parent tier names children in its draft before any ids
exist), and `name` (the node's user-facing name as identity).
Identity is per-tier; a single bundle commonly uses different
strategies for different tiers.

---

## A.2 The bundle abstraction

A.1 introduced the vocabulary; this chapter specifies how a
bundle declares concrete instances of it. A bundle is a
**typed-graph DSL**: a YAML schema declaring tiers, edges,
fragments, and context walks, plus the prompt templates the
tiers reference. The platform reads the bundle, validates the
declared graph for acyclicity and shape consistency, then runs
its reactive engine against whatever the bundle described.

This collapses what would otherwise be platform-side features —
per-tier readiness gates, post-commit fanout enqueues, fan-in
aggregation, cycle detection, cardinality checks — into a
small number of declarative primitives. Adding a new tier or
changing a chain's shape is a bundle edit, not a platform
change.

### A.2.1 Bundle layout on disk

A bundle lives at `bundles/<name>/` in the project repo. The
canonical layout is:

```
bundles/default/
  bundle.yaml          # top-level: name, version, tier + edge + fragment registry
  tiers/
    <tier>.yaml        # one file per tier declaration
  edges/
    <name>.yaml        # one file per named edge instance
  prompts/
    <tier>.md.liquid   # one Liquid template per LLM-generator tier
    review/
      <tier>.md.liquid # one Liquid template per tier's review prompt (when reviewed)
  flows/
    <flow>/flow.yaml   # one directory per flow declaration (A.5)
    <flow>/<prompt>.md.liquid
```

Files split by purpose. The top-level `bundle.yaml` carries
the registry — names + versions + the list of files
contributing each kind of declaration. The platform reads
`bundle.yaml` first, then loads each registered file. The
splitting is for editability and review-diffability; the
loaded bundle is the union.

Bundles ship in the project repo so `git clone` brings the
bundle with the project. A project can ship multiple bundles
(`bundles/default/`, `bundles/experimental/`) and switch
between them per branch or per flow. Bundle versioning is git
history; bundle authoring is editing files and committing them.

A project pins its bundle via a top-level `catapult.yaml` at
the repo root that names which bundle directory under
`bundles/` is active. Changing bundles is editing
`catapult.yaml` and committing; Catapult's reducer reads the
new bundle's schema on the next event after the change.

### A.2.2 Tier declarations

Each tier declaration sets the tier's scope, identity, fields,
handle, body grammar, generator, and context walks:

```yaml
# bundles/default/tiers/comparch.yaml
tier: comparch
scope: per(comp)
identity: id
fields:
  name:        draft.name
  techspec:    draft.techspec        # populates fragment via produces:
  pubapi:      draft.pubapi
  privapi:     draft.privapi
  policies:    draft.policies
handle:
  fields:    [id, name]
  fragments: [techspec, pubapi, policies]
draft:
  root_tag: comparch
  grammar: schemas/comparch.xsd
generator: llm
prompt: prompts/comparch.md.liquid
context:
  - self.parent.handle
  - self.parent.fulfills → resp.handle
  - self.parent.dependency → target.handle.fragments[pubapi]
produces:
  - fragment: { owner: self.parent, kind: techspec, authored: draft.techspec }
  - fragment: { owner: self.parent, kind: pubapi,   authored: draft.pubapi }
  - fragment: { owner: self.parent, kind: privapi,  authored: draft.privapi }
  - fragment: { owner: self.parent, kind: policies, authored: draft.policies }
```

Field-by-field:

- **`tier`** — the tier's name. Used as the directory key under
  the per-scope body path and as the lookup key in the
  scheduler's projection. Must be unique within the bundle.
- **`scope`** — how instances of the tier attach to the graph.
  The built-in scope expressions are `singleton`, `per(X)`
  (one per node of tier X), `child_of(X)` (minted by X's
  fanout), and the phased variants `per(X) × phase` /
  `child_of(X) × phase` for tiers that partition per-phase.
  Bundles use these as-is; the set is closed.
- **`scope_filter`** (optional) — a predicate further
  restricting which scope-parents the tier attaches to. E.g.
  `kind == domain AND has_edge(fanout_to_sub)`. The platform
  evaluates the filter at scheduler enumeration time.
- **`identity`** — `id`, `alias`, or `name`. How downstream
  references to this tier's nodes resolve.
- **`fields`** — scalar projection of body content. Each
  field expression names a path into the parsed body (e.g.
  `draft.techspec` reads the `<techspec>` element's text).
  Fields appear as columns on the tier's projection row.
- **`handle`** — the public surface. Names the subset of
  fields and fragments downstream tiers receive when they
  walk context edges to this tier's nodes. The handle is
  what other tiers see; the rest of the body is private.
- **`draft`** — the grammar the body file must parse against.
  `root_tag` is the expected outer element; `grammar` is the
  schema the platform validates against at commit time.
  Omit the entire `draft:` block for join-target tiers that
  hold no content of their own.
- **`generator`** — `llm` (default), `git_commit`,
  `synthesis`, `webhook`. See §A.1.7.
- **`prompt`** — path (relative to the bundle root) to the
  Liquid template for LLM generators.
- **`context`** — ordered list of edge-walk expressions the
  generator reads before producing a draft (§A.2.5).
- **`produces`** — optional declarations of fragments this
  tier's draft writes onto other nodes (§A.2.4).
- **`review`** (optional, not shown above) — when present,
  names a Liquid template at `prompts/review/<tier>.md.liquid`
  and a review grammar. The tier's draft → review → approval
  lifecycle runs through the platform's review machinery
  (§A.6).
- **`phased`** (optional boolean) — when true, the tier's
  scope key includes a `phase` dimension. Phase semantics
  live in §A.8.

### A.2.3 Edges

The platform recognizes five edge **types**, each with its
own machinery:

- **`fanout`** — parent-creates-children. A parent tier's
  draft property enumerates N children; the reducer mints
  them at parent approval. Cardinality applies per-parent.
- **`reference`** — general-purpose advisory edge. Cross-tier
  pointers resolved by the target's identity. The dominant
  edge type for "this tier reads that tier's handle as
  context." Cardinality optional.
- **`dependency`** — same-tier or cross-tier data dependency.
  Supports `graph_constraint: acyclic` enforced by the
  platform's libgraph integration. Used when downstream
  generation must see upstream content as ready.
- **`policy_application`** — cross-cutting application of a
  policy-bearing node to a target. The bundle declares which
  policy tiers apply to which target tiers and the
  reachability rules.
- **`synthesis`** — reverse aggregation. A tier with
  `generator: synthesis` aggregates its children's handles
  and publishes a handle that subscribers read via
  reference-style edges. The platform manages the
  first-pass readiness gate (synthesis fires when all
  required-content children are ready) and the staling-on-
  child-change behavior.

A bundle declares **named edge instances** typed against one
of these:

```yaml
# bundles/default/edges/fulfills.yaml
edge: fulfills
type: reference
source: comp
target: resp
declared_in: comp.draft.responsibilities[].@id
cardinality:
  source: { min: 1 }                  # every comp fulfills ≥1 resp
  target: { min: 1, max: 1 }          # every resp fulfilled by exactly 1 comp
```

```yaml
# bundles/default/edges/dependency.yaml
edge: dependency
type: dependency
source: comp
target: comp
declared_in: comp.draft.dependencies[].@to
cardinality:
  source: { min: 0 }
  target: { min: 0 }
graph_constraint: [acyclic, no_self_loop]
```

Cardinality endpoints use `{ min, max }` bounds.
`{ min: 1, max: 1 }` is exactly-one; `{ min: 1 }` is
at-least-one; `{ min: 0 }` is optional; the default `max` is
unbounded. Cardinality can be conditional
(`cardinality.when: kind == presentational`) and scoped
(`cardinality.per_source(parent_tier)`).

`declared_in` is the body-path expression naming where in
some tier's draft the edge gets emitted. The reducer parses
that path against each committed body and materializes the
edges into the projection.

`graph_constraint` names structural invariants the platform
enforces via libgraph: `acyclic`, `no_self_loop`, `tree`. A
bundle's full edge instance graph must be type-level acyclic
at bundle-load time; individual `dependency` edges with
`graph_constraint: acyclic` are checked per-instance during
projection.

### A.2.4 Fragments

A **fragment** is a named, authored prose block owned by a
specific node, readable by other tiers via
`handle.fragments`. Fragments expose sub-chunks of a node's
content at finer granularity than the whole document. A
dependent tier might only need the target's public API, not
its whole architecture doc; declaring `pubapi` as a fragment
makes the slice addressable.

Fragments are **authored only**. There is no derived-fragment
category; every graph-derived view a prompt needs is
expressible as a context-walk expression evaluated at read
time. This keeps the bundle DSL small (no serialization
templates) and pushes materialization decisions to the engine
layer where they're caching choices, not bundle semantics.

A tier can declare that its draft writes fragments owned by
**a different node** (typically `self.parent`) via the
`produces:` mechanism. The comparch tier example in §A.2.2
writes its parent comp's `techspec`, `pubapi`, `privapi`, and
`policies` fragments. Readers walking context edges to the
parent pick those fragments up without knowing which tier
authored them.

Fragment kinds form a closed vocabulary per bundle. Adding a
new kind is a bundle edit (declare the kind under
`bundle.yaml`'s fragment registry, reference it from a
tier's `handle` and / or `produces`).

**Fragment as the unit of regeneration.** When a generator
re-runs (because upstream context changed, a flow asked for
it, or the user fed back feedback), the output is a
fragment-scoped delta — only the fragments the new draft
actually changes get new content; untouched fragments stay
at their prior values. This makes propagation cheap: output
tokens scale with the changed slice, not the whole document.
Custom generators (§A.1.7) must respect this contract.

### A.2.5 Context walks

A tier's `context:` is an ordered list of typed edge-walk
expressions its generator reads before producing a draft.
Each entry resolves to handle content, fragment content, or a
synthesis view.

```yaml
comparch:
  context:
    - self.parent.handle
    - self.parent.fulfills → resp.handle
    - self.parent.decomposed_by(subresp)
    - self.parent.dependency → target.handle.fragments[pubapi]
    - self.parent.domain_parent → target.synthesis
```

Walk anatomy:

- **`self`** — the scope being generated.
- **`self.parent`** — the scope-parent (the node referenced
  by the tier's `scope: per(X)` expression).
- **`.<edge_name>`** — follow a declared edge by name.
- **`→ <tier>.<projection>`** — type the walk's target and
  name what to read from it. `.handle` reads the full handle;
  `.handle.fragments[<kind>]` reads one fragment slice;
  `.synthesis` reads a synthesis tier's aggregated handle.
- **Cardinality-many** walks yield collections. A
  `decomposed_by(subresp)` walk yields every subresp; the
  generator's prompt template iterates them.

Context is the **only** readiness signal the scheduler needs.
A `(tier, scope)` pair is **ready** when every traversal in
its `context:` resolves to content in the *ready* state —
the producing tier's instance is approved, or its synthesis
handle has populated. Cardinality-many traversals require
*all* targets ready by default.

Two scheduling behaviors that would otherwise need dedicated
platform machinery fall out of this rule:

- **First-pass synthesis gate.** A synthesis tier generates
  when every child's required content is approved. Not a
  special predicate — just the default "cardinality-many
  requires all targets ready" applied to a synthesis tier's
  child-aggregation walk.
- **Cross-tier subscription gate.** A presentational comp
  waiting for its domain parent's synthesis is just the
  context entry `self.parent.domain_parent → target.synthesis`
  failing to resolve until the synthesis tier's handle
  populates.

Context declarations make scheduling **inspectable**. The
dashboard renders each tier's context as a dashed overlay on
the graph showing where a prompt's content comes from;
missing or stale sources are the complete set of things
blocking a generation.

### A.2.6 Predicate language

Six operator families cover every conditional the bundle
DSL needs. Bundle authors use these in `scope_filter`,
`cardinality.when`, edge `constraint`, and edge
`graph_constraint`:

- **Comparison** — `==`, `!=`, `<`, `>`, `<=`, `>=`
- **Boolean** — `AND`, `OR`, `NOT`
- **Edge counting** — `has_edge(type)`,
  `count(edge_path) op N`
- **Existential** — `exists(edge_path where predicate)`
- **Universal** — `all(edge_path → field)`,
  `any(edge_path → field)`
- **Reachability** — `reaches(source, target, via=[edge_types])`

Field access is `self.field` for scalars,
`self.edge(type).target.field` for traversals, `self.parent`
for the scope-parent. Aggregates over traversals
(`count`, `any`, `all`, `exists`) are permitted; arithmetic,
string manipulation, and regex are not — the predicate
language is deliberately not Turing-complete.

The language appears in exactly four slots:

- **`scope_filter`** on a tier — restrict which scope-parents
  the tier attaches to.
- **`cardinality.when`** on an edge — restrict which nodes a
  cardinality bound applies to.
- **`constraint`** on an edge — value conditions on an edge's
  endpoints (e.g. `source.kind == presentational AND
  target.kind == domain`).
- **`graph_constraint`** on an edge — named structural
  invariants (`acyclic`, `no_self_loop`, `tree`).

**Named predicates as reusable expressions.** A bundle can
name a predicate it reuses across multiple declarations. The
bundle's optional `predicates.yaml` registers named entries,
each of which is a predicate-language expression composed of
the six operator families:

```yaml
# bundles/default/predicates.yaml
predicates:
  is_domain:           kind == domain
  is_presentational:   kind == presentational
  has_subcomps:        count(decomposed_by(subcomp)) > 0
  awaits_domain_fanin:
    kind == presentational
    AND any(domain_parent → target.synthesis_ready)
```

Once registered, the name is usable anywhere a predicate is
expected:

```yaml
tier: presentational_comparch
scope: per(comp)
scope_filter: awaits_domain_fanin
```

Named predicates can reference other named predicates
(`is_presentational AND count(...) > 0`), letting bundle
authors build a small vocabulary of reusable patterns. The
language stays closed — every named predicate is a
composition of built-in operators, validated at bundle-load
time. The bundle contains no code; there is no admin-approved
escape hatch; there is no runtime evaluation of bundle-
provided functions. Anything the six operator families can't
express is not expressible in the bundle DSL, which is a
correctness property the platform leans on.

### A.2.7 The scheduler as reactive runtime

The scheduler is three rules:

1. **Enumerate.** For every tier in the loaded bundle, find
   every `(tier, scope_parent)` pair where `scope_parent`
   exists in the current projection and satisfies the tier's
   `scope_filter`.
2. **Evaluate readiness.** Does every entry in the tier's
   `context:` resolve to a ready source for this scope pair?
3. **Write the ready projection.** For every pair that
   passes readiness, write a row to the `ready_scopes`
   projection. The agent reads this projection through MCP to
   decide what to draft next.

The scheduler is **state-driven**: readiness is a query
against the current projection, not a reaction to individual
events. This is what makes replay trivial — the same query
that answers "is this ready now?" also answers "was this
ready at sequence T?" by running against the projection at
sequence T. And it's what keeps the scheduler stateless — no
in-memory pending-set to corrupt, just a function from
projection state to ready set.

Two triggers drive the readiness query in practice:

- **Fast path.** A reducer event commits that plausibly
  changes some tier's readiness; the scheduler re-evaluates
  the affected `(tier, scope_parent)` pairs immediately.
  Wired through Phoenix.PubSub on a per-project topic the
  scheduler subscribes to.
- **Sweeper.** A low-frequency background loop (configurable
  default 30-60s) re-evaluates every enumerable pair against
  current state. Catches anything the fast path missed and
  provides an always-converging lower bound on correctness.

Critically, the scheduler **does not enqueue jobs**. It does
not initiate work. It writes the `ready_scopes` projection.
Whether anything happens with that projection is up to the
agent — Claude Code reads it via MCP, picks a scope, drafts
the body, commits, and the cycle repeats. The server reacts;
it does not drive.

**Staling is the reactive dual.** When an approved node
changes (re-approval with new content, force-reset, body
edit), the scheduler walks edges whose carried payload
depends on the changed slice and marks dependents stale. A
stale tier re-enters the readiness loop on the next pubsub
fire or sweeper pass; if its context is still ready (or
re-resolves after upstream regens), it shows up as ready
again. The agent sees the freshly-ready scope and may choose
to regenerate. Staling does not bypass review — a stale
tier's next generation is a new draft that goes through the
same approval lifecycle.

### A.2.8 Acyclicity and graph constraints

Two acyclicity layers:

- **Type-level.** The graph of edge declarations — tiers as
  nodes, named edge instances as directed edges from source
  tier to target tier — must be acyclic. Cycles among tier
  types would mean tier A's readiness can depend on tier B's
  content which can depend on tier A's content, so no tier
  is ever ready first. The platform checks this at
  bundle-load time using libgraph; a bundle with type-level
  cycles fails to load.
- **Instance-level.** Edges declared with
  `graph_constraint: acyclic` are checked per-instance at
  projection time. A `dependency` edge from `comp_a` to
  `comp_b` and another from `comp_b` to `comp_a` produces a
  cycle that the platform rejects at commit (the offending
  commit fails validation, the body file is rejected, the
  agent sees a typed error and can retry).

The `tree` graph constraint enforces "every target has
exactly one incoming edge of this type." `no_self_loop`
rejects edges where source and target resolve to the same
node. These are checked at the same projection-time pass as
acyclicity.

### A.2.9 Liquid templating

Prompt templates are **Liquid**. The bundle's
`prompts/<tier>.md.liquid` files are evaluated against a
context derived from the tier's `context:` walks: each named
walk becomes a Liquid variable, with cardinality-many walks
becoming iterable arrays.

A small comparch prompt fragment to illustrate:

```liquid
# Draft component architecture for {{ self.parent.name }}

This component fulfills:
{% for resp in fulfills %}
  - {{ resp.name }}: {{ resp.intent }}
{% endfor %}

The component depends on:
{% for dep in dependencies %}
  - {{ dep.name }} ({{ dep.pubapi | indent: 4 }})
{% endfor %}
```

The Liquid context the platform makes available:

- **`self`** — fields and handle of the scope being
  generated, where they exist (the body hasn't been drafted
  yet, so most projections are empty pre-draft).
- **One variable per named context walk.** A walk named
  `fulfills` in the tier's `context:` becomes
  `{{ fulfills }}` in the template.
- **`feedback`** — when this generation is a regen with
  user-provided feedback, the feedback text.
- **`prior_review`** — when this generation is a regen
  following a review, the prior review's findings.

Liquid was chosen over markdown-with-substitution or full
templating engines for three reasons:
- **Safety.** Liquid is sandboxed by design; templates can't
  execute arbitrary code.
- **Existing ecosystem.** Elixir's Solid library implements
  Liquid faithfully; no new templating semantics to learn.
- **Bundle authorability.** Liquid's `{% for %} {% if %}`
  syntax is approachable to anyone who has written Jekyll or
  Shopify themes; bundle authors can produce sophisticated
  prompts without a Python or Ruby runtime.

Review prompts at `prompts/review/<tier>.md.liquid` follow
the same shape with one addition: the variable
`{{ draft }}` carries the body being reviewed.

### A.2.10 Bundle loading and versioning

A bundle is loaded by parsing every file under
`bundles/<active>/`, validating cross-references (every edge's
source and target tiers must exist; every fragment kind
referenced in a tier's `handle` or `produces` must be in the
registry), and computing the tier-graph + edge-type acyclicity
check.

Bundle versioning is git history. The project repo records
the bundle directory's path and the active bundle's version
string in `catapult.yaml` at repo root. When the user commits
a change to a bundle file, Catapult's reducer notices on the
next fetched commit and re-loads the bundle. If the new
bundle fails validation (cycles, missing references, grammar
errors), the load fails and the previously-loaded bundle
remains active; the failing commit's load error is surfaced
in the dashboard.

Multiple bundles can coexist in `bundles/`. A project may
switch its active bundle by editing `catapult.yaml`'s
pointer. Switching does not migrate projection state — if the
new bundle declares tiers the old one didn't, those tiers
have no nodes until generators fire; if the old bundle had
tiers the new one drops, the orphaned projection rows stay
in storage but no longer appear in queries. Most projects
will run one bundle for their lifetime; switching is an
escape hatch for experimentation, not a routine operation.

---

## A.3 The reactive engine

A.2 specified the bundle DSL and the scheduler's three rules
abstractly. This chapter specifies how those rules run on
Postgres + Commanded + Phoenix.PubSub. The engine has four
moving parts: the **event log** (append-only history of every
command's effect), the **reducer** (the function that applies
events to projections), the **projections** (the read models
the scheduler queries and the dashboard renders), and the
**reactive scheduler** (the loop that watches the projection
and writes the ready-set).

### A.3.1 The event log

Every state change goes through the event log. A command
issued via MCP (e.g. `CommitDraft`, `ApproveDraft`,
`OpenFlow`) is validated by a Commanded aggregate against
the current projection; if accepted, the aggregate emits one
or more events, which are persisted to the log and then fed
to the reducer for projection update. The log is the source
of truth; projections are derived.

Events carry: `event_id` (ULID), `project_id`, `sequence`
(per-project monotonic), `event_type` (a string like
`DraftCommitted` / `ReviewWritten` / `Approved`), `aggregate_id`
(the aggregate instance that emitted), `payload` (a JSON
object whose shape is per-event-type), `inserted_at`
(timestamp), and `actor_id` (the user whose command produced
it). The schema is uniform across all event types; per-type
shape lives in the payload.

The log is **append-only**. There is no edit, no delete, no
compaction-by-rewrite. State corrections happen by appending
corrective events (e.g. `DraftDiscarded`, `ProjectionReset`)
that the reducer interprets. This is what makes replay
trivial and makes the event log the audit trail without
additional machinery.

**Per-project ordering, no cross-project ordering.** The
sequence number is monotonic per project. Two projects can
interleave commits without coordination because their
aggregates and projections are independent.

### A.3.2 The reducer

The reducer is a function `(projection_state, event) →
new_projection_state`. It's pure — given the same starting
state and event, it produces the same result every time —
and it's complete: every event the system can emit has a
reducer branch. Reducer correctness is the single most
important invariant in the engine, because every read model
in the system is its output.

The reducer's branches are organized by event type. Each
branch knows which projection tables the event touches and
applies the changes in a single Postgres transaction
together with the event log insert. This is what makes the
log + projection pair consistent: either both update or
neither does.

Some event types fan out to multiple projection updates.
`ApproveDraft` for a tier with `fanout` edges, for example,
mints child nodes for each enumerated child in the draft;
the reducer reads the draft body, parses the fanout
property, mints child rows in the node projection, and
writes the edge projection — all in the same transaction.
The bundle's fanout declaration tells the reducer where in
the parent's body to look and which tier to mint into; the
reducer is generic over those parameters.

**Rebuild-from-zero correctness.** A property the platform
enforces in tests: running the reducer against the full
event log from sequence 0 produces byte-identical projection
state to incremental application. Any branch that fails this
property is a bug. The rebuild is also the platform's
recovery mechanism — a projection corrupted by operator
error or by a bug in a now-fixed reducer branch is restored
by truncating projection tables and replaying.

### A.3.3 Projections

Projections are denormalized read models. They exist solely
for query efficiency — every projection's content is fully
recoverable from the event log. The platform writes several
universal projections; the bundle's tier declarations
implicitly add per-tier projection columns.

The universal projections:

- **`nodes`** — one row per scope. Columns: `node_id`,
  `project_id`, `tier`, `scope_key` (JSON of the tier's
  scope dimensions), `status` (one of `absent`, `drafted`,
  `reviewed`, `approved`, `stale`), `current_draft_id`,
  `current_review_id`, `body_sha` (the git sha the body file
  was committed at), `inserted_at`, `updated_at`. Per-tier
  field projections live in `nodes.fields` as a JSON column
  derived from body fields per the tier's `fields:`
  declaration.
- **`edges`** — one row per edge instance. Columns:
  `edge_id`, `project_id`, `edge_name` (the bundle's named
  instance), `source_node_id`, `target_node_id`,
  `inserted_at`. The reducer derives edges from body content
  per the tier's `declared_in` paths.
- **`fragments`** — one row per authored fragment. Columns:
  `fragment_id`, `project_id`, `owner_node_id` (the node the
  fragment is attached to), `kind`, `content`, `author_tier`
  (the tier whose draft wrote it via `produces:`),
  `author_node_id`, `inserted_at`.
- **`drafts`** — draft lifecycle records. Columns:
  `draft_id`, `project_id`, `node_id`, `body_sha`,
  `committed_at`, `status` (`pending` / `approved` /
  `discarded`), `review_id` (the AI review attached to this
  draft, if any). One node can have at most one `pending`
  draft at a time.
- **`reviews`** — review records. Columns: `review_id`,
  `project_id`, `draft_id`, `score` (per the bundle's review
  grammar), `findings` (JSON), `body_sha` (the git sha the
  review file was committed at), `kind` (`ai` or `human`),
  `inserted_at`.
- **`ready_scopes`** — the reactive scheduler's output. One
  row per `(tier, scope_key)` pair currently ready to
  generate. The agent queries this projection to decide what
  to draft next.
- **`staleness`** — per-node staleness markers. A node with
  a row in this table has had an upstream change since its
  last approval; its next regen consumes the marker.
- **`flows`** — active flow records. One row per open flow on
  a project, with the flow's seed, current walk state, and
  completion-predicate status.

Per-bundle projections (tier-specific field columns,
edge-instance-specific projections, fragment-kind-specific
materialized views) are derived from the bundle's
declarations at load time. The engine writes generic
projections; specifics fall out of generic columns + bundle
semantics.

### A.3.4 The reactive scheduler

The scheduler subscribes to a per-project Phoenix.PubSub
topic the reducer broadcasts on after every committed event.
On receive, it runs the three-rule loop from §A.2.7 against
the current projection: enumerate, evaluate readiness, write
`ready_scopes`. The writes are diffs — the scheduler reads
the current `ready_scopes` content, computes the new set,
inserts rows that appeared and deletes rows that disappeared.

The fast-path response time is bounded by how quickly the
scheduler can run readiness evaluation against the new
state. For most events, only a small number of `(tier,
scope_key)` pairs need re-evaluation — the ones whose
context-walk dependencies were touched by the event. The
scheduler uses the bundle's edge declarations to compute the
affected set; it doesn't re-evaluate every tier on every
commit.

**The sweeper.** A background loop runs every 30-60 seconds
(configurable per project) and re-evaluates every enumerable
`(tier, scope_key)` pair regardless of recent activity. The
sweeper exists as a consistency floor: if the fast path ever
misses an update (because of a bug in the affected-set
computation, a missed pubsub message, a process restart),
the sweeper catches it within the configured interval.

The sweeper is also what handles "this scope became ready
because some non-event-driven condition changed" — typically
not relevant in the current spec but useful as a hedge.

### A.3.5 Replay and recovery

Two operations the engine supports out of the platform:

- **Replay to sequence T.** Useful for debugging "was this
  scope ready at time T?" The engine reads events 0..T from
  the log, applies them to a fresh in-memory projection,
  runs the scheduler against that state, returns the
  ready-set as of T. No persistent state is touched.
- **Projection rebuild.** When a projection is suspected
  corrupted (operator error, reducer-branch bug fix), an
  admin runs the rebuild operation. The engine creates a
  shadow set of projection tables, replays the full event
  log into them, validates against invariants, then atomic-
  swaps the shadow into place. The project is read-only
  during the swap.

Rebuild-from-zero correctness (§A.3.2) is what makes both
operations safe.

### A.3.6 Snapshots

For projects with very long event logs, rebuild becomes
expensive. The engine supports periodic snapshots — a saved
projection state at sequence N — so rebuild starts from
snapshot N and replays from there. Snapshots are taken on a
configurable cadence (default: every 10,000 events per
project) and stored alongside the event log.

Snapshots are an optimization, not a source of truth. A
snapshot whose content disagrees with replay-from-log is a
bug; the platform's invariant tests catch this in CI.

### A.3.7 What the engine does not do

The engine does not call LLMs, does not orchestrate flows,
does not enqueue work for an agent to do, and does not push
notifications to anyone. It reacts to commits and updates
projections. The agent (Claude Code) is the only thing that
calls LLMs and the only thing that decides what to do next;
the engine's job is to make sure the agent has a current,
correct, fast-to-query picture of project state when it
asks.

---

## A.4 The agent driver

Claude Code is the only thing that drives generation, runs
LLM calls, composes bodies, writes files to disk, and
commits to git. This chapter specifies how CC connects to
Catapult, what tools it has, and how the commit flow works
in detail.

### A.4.1 Remote MCP

Catapult exposes an MCP server over HTTPS on the central
deployment. CC connects via the remote-MCP transport using
a per-user JWT for authentication. There is no local CC
subprocess of the Catapult server, no local stdio MCP
transport — CC opens an HTTPS connection to
`https://catapult.<domain>/mcp/<project_id>` and talks to
the Catapult server directly.

The MCP server is the only network surface CC interacts
with at runtime. The dashboard is a separate Phoenix
LiveView app served from the same Catapult instance but
unrelated to the MCP channel; CC does not read or write the
dashboard.

### A.4.2 Read tools

The MCP server exposes a small set of read tools that query
Catapult's projections. The bundle's tier set determines
parts of the shape; the platform vocabulary is:

- **`list_ready_scopes`** — returns rows from the
  `ready_scopes` projection, optionally filtered by tier or
  flow. This is CC's primary "what should I work on" query.
- **`get_scope_state`** — for a `(tier, scope_key)` pair,
  returns the node row + current draft + current review +
  body_sha + status flags.
- **`get_context`** — for a `(tier, scope_key)` pair,
  evaluates the tier's `context:` walks against the current
  projection and returns the result, plus the Liquid-rendered
  prompt template ready for CC to feed to the LLM. This is
  the tool that replaces siege's `siege.cli get-context`.
- **`get_handle`** — for a `(tier, scope_key)` pair, returns
  the handle (fields + named fragments) for downstream
  walks. Used by CC when assembling context manually.
- **`get_review_context`** — for a draft, returns the review
  prompt's rendered Liquid + the original draft body. Used
  when CC runs the AI review pass.
- **`get_phase_plan`** — returns the current phase plan
  projection. Phased flows query this to walk phases in
  order.
- **`get_flow_state`** — for an open flow, returns the
  flow's current walk position, completed scope visits,
  pending visits.
- **`list_projects`** — returns the projects the
  authenticated user has access to.

All read tools are idempotent. Calling them multiple times
in close succession returns consistent results as of the
last committed event the server has processed; there's no
"stale read" surprise.

### A.4.3 Write tools

Write tools fire commands at Commanded aggregates. The
commands the platform recognizes:

- **`commit_draft`** — CC has written a body file to git,
  committed, and pushed. CC calls this with `(project_id,
  tier, scope_key, body_sha)`. The server fetches the branch
  at `body_sha`, reads the body file, validates against the
  bundle's grammar, runs the per-tier reducer branch, emits
  a `DraftCommitted` event. Returns success or a typed
  validation error.
- **`commit_review`** — same shape, but for a review file.
  CC writes the review.md, commits, pushes, then calls this
  with `(project_id, draft_id, body_sha)`. Server fetches,
  validates against review grammar, emits `ReviewCommitted`.
- **`approve_draft`** — `(project_id, draft_id)`. The
  Commanded aggregate validates that the draft is in
  `pending` state, that no other approved draft exists for
  the scope without a discard event in between, and that
  the bundle's `cardinality` rules on edges the approval
  produces are satisfied. Emits `DraftApproved` plus fanout
  events for any child nodes the parent tier mints.
- **`discard_draft`** — `(project_id, draft_id, reason)`.
  Marks the draft discarded so a regen can produce a new
  one. Used when the human reviewer rejects.
- **`request_regeneration`** — `(project_id, tier,
  scope_key, feedback)`. Marks the scope's current approved
  content stale and the scope itself ready for a new draft.
  Used by the human reviewer when iterating on an approved
  artifact.
- **`open_flow`** — `(project_id, flow_name, seed)`. Opens
  a flow (§A.5). The aggregate validates that no conflicting
  flow is open per the lobby (§A.8).
- **`advance_flow`** — `(project_id, flow_id, visit_id)`.
  Marks a flow's walk as having visited the named scope;
  the next ready visit shows up in `get_flow_state`.
- **`close_flow`** — `(project_id, flow_id)`. Closes an
  open flow. The aggregate validates that the flow's
  completion predicate is satisfied.

Write tools return either success (with the new event
sequence) or a typed error. Failures are first-class data CC
can pattern-match on, not exceptions to recover from.

### A.4.4 The commit flow

A draft commit, end to end:

1. CC queries `get_ready_scopes`, picks a scope to draft.
2. CC queries `get_context` for that scope. The server
   evaluates the tier's context walks against the current
   projection, renders the Liquid prompt template with
   walk results as variables, returns the rendered prompt.
3. CC runs the LLM locally. The LLM produces a body
   conforming to the tier's grammar.
4. CC writes the body to `<tier>/<scope_path>/body.md` in
   the local project repo, commits, pushes to the project's
   git remote.
5. CC calls `commit_draft` with the new sha.
6. The server fetches the branch at that sha. Reads the
   body file. Validates against the bundle's grammar.
   - If validation fails: the server returns the typed
     error to CC. CC reads it, decides whether to retry
     (regenerate with the error as feedback) or surface to
     the user.
   - If validation passes: the reducer applies events that
     update the `nodes` projection (`status: drafted`,
     `body_sha: <sha>`), the `drafts` projection (new
     `pending` row), the `fragments` projection (any
     `produces:` declarations), the `edges` projection (any
     `declared_in` edge derivations). Phoenix.PubSub fires.
     The scheduler runs. The agent sees updated
     `ready_scopes` on its next query.

The whole flow takes one round-trip to the server per
commit. CC does not poll for the server to confirm; the
`commit_draft` response is the confirmation.

### A.4.5 Authentication

Per-user JWTs issued via the dashboard's login flow. Each
project the user has write access to gets a separate JWT
scope; CC connects to `https://catapult.<domain>/mcp/<project_id>`
with the JWT in the Authorization header, and the server
validates the token grants write access to that project.

The server's git fetches use the project's stored GitHub
OAuth token, which the project owner provides at project
creation (§A.9). The fetch credential is server-side; CC
never sees it.

### A.4.6 Concurrency

Only one driver per project at a time. The lobby (§A.8)
enforces this at the Commanded aggregate level: a write
command from CC includes an implicit "driver session" the
server tracks; conflicting commands from a second session
fail with a typed `LockHeldByOtherSession` error.

The single-driver constraint is what lets the rest of the
engine assume there are no concurrent writes to the same
project. Cross-project writes proceed in parallel.

---

## A.5 Flows

A **flow** is a structured way to advance a project's chain
in response to a specific stimulus: a user-supplied feature
request, a refactor proposal, an upstream feedback comment.
Flows are bundle-declared schema deltas — a flow adds
additional tiers and edges to the bundle's base schema while
it's active, the reactive engine runs against the merged
graph, and the flow ends when no more `(tier, scope)` pairs
are enqueueable.

This chapter specifies the flow mechanism. The default
bundle's specific flows (feature-request, refactor,
bug-fix-propagation, downward-propagation,
upward-propagation) are catalogued in Part B §B.6.

### A.5.1 Flows as schema deltas

Each flow lives at `bundles/<bundle>/flows/<flow-name>/` in
the bundle directory. The flow directory contains:

- **`flow.yaml`** — the schema delta. Declares the flow's
  seed shape, any new tiers the flow adds (typically
  planning tiers), and any new edges that wire the flow's
  tiers into the base schema.
- **Prompt files.** Liquid templates for the flow's
  planning tiers' prompts.

A flow is **not** a state machine. It's a graph delta. When
a flow opens, the bundle's effective schema becomes
`base ∪ flow_delta`. The reactive scheduler runs against
the merged graph; the flow's new tiers and edges participate
in readiness evaluation exactly the same way base tiers do.
The flow doesn't have an imperative driver; it advances by
virtue of the scheduler finding ready scopes in the merged
graph and the agent generating them.

### A.5.2 Seeds

A flow opens with a **seed** — the input that motivated the
flow. Different flows take different seed shapes:

- A feature-request flow's seed is prose: the user describes
  what they want.
- A refactor flow's seed is a description of the structural
  change.
- A bug-fix flow's seed is a defect report.
- A downward-propagation flow's seed is a re-approval at an
  upstream tier whose effect needs to propagate.
- An upward-propagation flow's seed is feedback from a
  downstream scope that argues against an upstream
  decision.

Seed shape is bundle-declared per flow. The platform
validates the seed against the declared shape at `open_flow`
time.

### A.5.3 Walks

A flow declares a **walk primitive** that determines how
its planning tiers visit base-schema scopes. Two primitives
the platform recognizes:

- **`downward_cascade`** — start at the seed's anchor scope,
  walk downstream edges (typically `fanout` and `dependency`)
  to enumerate affected scopes, generate a planning artifact
  per affected scope in dependency order.
- **`up_then_down`** — start at the seed's anchor scope,
  walk upstream to the point at which a planning decision
  has to be made, generate a plan there, then walk down to
  re-plan affected downstream scopes.

A flow declares which primitive it uses via `invokes:` in
its `flow.yaml`. Most flows use `downward_cascade`; only
upward-propagation uses `up_then_down`.

### A.5.4 Planning tiers

Most flows introduce one or more **planning tiers** — tiers
whose body is a plan-for-this-scope artifact that downstream
generation reads. A planning tier's scope is `per(target_tier)`
where target_tier is a base-schema tier the flow visits. The
planning tier's body is a prompt-rendered plan; downstream
generation of the target_tier consumes the plan via a
context walk.

Planning tiers participate in the same review lifecycle as
base tiers — the plan goes through AI review and human
approval before downstream generation can consume it.

### A.5.5 Flow completion

A flow ends when no more `(tier, scope)` pairs in the
merged schema are ready and enqueueable. The platform
detects this as part of the scheduler loop: when the flow's
own tiers' ready set is empty and every base-schema scope
the flow staled has been re-approved or explicitly skipped,
the flow's completion predicate fires.

The completion predicate is bundle-declared per flow
(typically as a named predicate in the bundle's
`predicates.yaml`). When it fires, the platform emits a
`FlowReadyToClose` event; the agent calls `close_flow` to
finalize.

### A.5.6 Scaffolding is not a flow

The scaffolding pattern — walk the chain from the input doc
through every base-schema tier, drafting and reviewing each
scope in dependency order — is **not** a flow. It's the
base schema's default behavior with no flow active. The
agent's `/scaffold` command queries `list_ready_scopes`
repeatedly and drafts each ready scope until the chain has
populated end-to-end.

This is why scaffolding doesn't need a `flows/scaffold/`
directory in the bundle — there's no schema delta; the base
schema is already what scaffolding walks.

---

## A.6 Review, feedback, approval

Every tier with a `review:` declaration carries a
draft → AI review → human review → approval lifecycle. This
chapter specifies the lifecycle and the agent / dashboard
surfaces that act on it.

### A.6.1 The lifecycle

1. **Draft commit.** CC writes a body, calls `commit_draft`,
   the server validates + commits. The node enters status
   `drafted`. The bundle's tier declaration may carry a
   `review:` flag; if absent, the draft is eligible for
   direct approval and skips steps 2-3.
2. **AI review.** With `review:` set, the platform's
   scheduler marks the draft as needing review. CC sees it
   in `list_ready_scopes` with tier filter `review`. CC
   calls `get_review_context`, runs the LLM with the
   bundle's review prompt template, writes the review.md
   file, commits, calls `commit_review`. The draft enters
   status `reviewed`.
3. **Human review.** The dashboard surfaces the draft +
   AI review side-by-side. A human reviewer reads the AI
   review, may apply individual findings as
   feedback-for-regen (which fires `request_regeneration`)
   or accept the draft as-is.
4. **Approval.** Human reviewer (or the project owner)
   calls `approve_draft` via the dashboard. The aggregate
   validates the approval is legal (the draft is `pending`,
   no other approved draft for the scope exists undiscarded,
   any bundle-declared approval predicates pass). The node
   enters status `approved`. Downstream readiness queries
   start seeing this scope as content-bearing.

### A.6.2 AI reviews are advisory

The platform contract is that approval does not depend on
the AI review having completed or passed. The reviewer's
score doesn't gate; their findings are suggestions the
human can apply or ignore. This is what lets reviews run
asynchronously to approval — the agent can run the review
in parallel with the human looking at the draft.

A bundle can declare a tier where AI review is mandatory
by setting `review: { required: true }`. The platform then
gates `approve_draft` on the review having committed. This
is bundle policy, not platform policy.

### A.6.3 Findings as structured data

Reviews emit findings in the bundle's review grammar (the
default bundle's grammar is the structured `<review>` block
siege uses today, with intro + score + handles-structure +
architectural-decisions sections). Each finding has an `id`
the dashboard renders as a clickable apply-as-feedback
button.

When a user clicks apply-as-feedback on a finding, the
dashboard fires `request_regeneration` with the finding's
prose as the feedback payload. The new draft's prompt
renders `{{ feedback }}` with that text; the LLM
incorporates the finding.

### A.6.4 Multiple drafts per scope

A scope can have at most one `pending` draft at a time. A
regen request discards the current pending (emits
`DraftDiscarded` first) before the new draft commits. The
draft projection keeps history — every draft a scope has
ever had, with status and the body sha it referenced —
which is what makes the per-scope draft history queryable
for audit and for prior-draft context on regens.

### A.6.5 Approved-content staleness

When an upstream change stales an approved scope (§A.3.4),
the staleness marker doesn't auto-discard the approval. The
approved body remains the source of truth for downstream
queries; the staleness marker is a hint to the reviewer
that this scope may need regenerating soon. The reviewer
chooses when to fire `request_regeneration`.

This is what makes propagation incremental rather than
cascading. A single upstream re-approval doesn't
automatically destroy every downstream approval; the
project's drift accumulates as staleness markers until a
flow or a manual regen consumes them.

---

## A.7 Phased delivery

Some artifacts in a project partition across delivery
phases: an implementation gets one body per phase the
component participates in, a fan-in synthesis recomputes per
phase as the as-built reality changes. The bundle's tier
declarations name which tiers are phased; this chapter
specifies how the platform tracks phases.

### A.7.1 Phase as scope dimension

A tier with `phased: true` carries an additional `phase`
dimension in its scope key. The body file path for a phased
scope includes the phase: `<tier>/<scope_path>/p<phase>/body.md`.
Phased tiers in the bundle declare their scope as
`per(parent_tier) × phase`; the platform recognizes the
composition and enumerates `(parent, phase)` pairs.

Each phase is an integer ≥ 1. There is no `phase 0`;
unphased tiers simply don't carry the dimension.

### A.7.2 The phase plan

The phase plan is a projection: `phase_plan` table, one row
per `(project_id, phase, scope_key)` triple. The rows say:
"in phase N, the project participates in this scope." The
plan is computed by a bundle-declared `plan_rule` that takes
the current `nodes` + `edges` state and produces phase
assignments.

The default bundle's plan rule (Part B §B.5) assigns
features to phases based on user choice (the user pins each
feature to a phase via the dashboard), then propagates phase
assignments down the chain: a responsibility is in phase N
if any of its owning features are; a component is in phase
N if any of its owning responsibilities are; etc. Other
bundles can declare different plan rules.

The plan recomputes whenever a body that affects assignment
changes. Plan changes mark phased-tier scopes stale where
their phase membership changed.

### A.7.3 Phase walking

The agent walks phases via the `get_phase_plan` MCP tool.
For a phased flow, CC enumerates phases in ascending order,
queries ready scopes within each phase, drafts them, then
advances to the next phase when the prior phase's scopes
have approved.

The bundle can declare a flow that explicitly walks phases
(`/run_phase N` in the default bundle's skill suite is one);
the platform's scheduler treats phased tiers the same as
unphased ones — readiness is per-`(tier, phase, scope_key)`
triple. The "advance one phase at a time" semantics are
agent-side workflow.

### A.7.4 Cross-phase delta context

A phased tier's prompt may need to see "what's different in
this phase from prior phases." The bundle declares this as a
context walk that compares the current phase's scope to the
prior phases' state: typically `self.prior_phases →
target.handle` for the scope's identity across all prior
phases.

This is plain bundle DSL — there is no special platform
machinery for cross-phase context. The walk is just a query
the engine evaluates at `get_context` time.

### A.7.5 Plan-change flow

When the user changes a phase assignment — moves a feature
from phase 2 to phase 3, splits a phase, drops a phase
entirely — the plan-change flow opens. The flow's seed is
the plan diff; its walk visits every scope whose phase
membership changed and regenerates the affected
phased-tier bodies in dependency order.

The plan-change flow is one of the default bundle's flows
(Part B §B.6).

---

## A.8 Lobby

The platform enforces "one driver per project at a time"
through the **lobby** — a per-project mutex held by an
active driver session.

### A.8.1 The mutex

When CC opens an MCP connection to a project, the server
opens a driver session and grants the lobby mutex if it's
free. The session ID is associated with the JWT; the lobby
record in Postgres has `(project_id, session_id,
opened_at)`. The session ID rides on every write command CC
issues; the Commanded aggregate validates that the session
ID matches the lobby holder before processing.

A driver session expires after 30 minutes of inactivity
(configurable per project). Heartbeats from CC extend the
session. On expiry, the session releases the lobby; a new
session can claim it.

### A.8.2 Lobby contention

When CC tries to open a session on a project whose lobby is
held, the connection returns a typed
`LobbyHeldByOtherSession` error with the holder's session
ID and opened-at timestamp. CC surfaces this to the user;
the user can wait, contact the holder, or (if they're the
project owner) force-release the lobby via the dashboard.

There is no queue. The "wait" pattern is the user retrying
the connection after the holder finishes; the platform does
not orchestrate handoffs.

### A.8.3 Read access ignores the lobby

The lobby gates writes only. The dashboard's reads, the
collaborators' git pulls, the MCP server's read tools are
all unaffected — many users can read a project's state
simultaneously. Only the write mutex is exclusive.

---

## A.9 Multi-project and credentials

A Catapult instance hosts multiple projects belonging to
multiple users. This chapter specifies the project entity,
how users gain access, and how Catapult handles per-project
git credentials.

### A.9.1 Projects

A project is a Postgres entity with:

- `project_id` (ULID), `name`, `description`
- `owner_user_id` — the single user who has write access
- `git_remote_url` — the URL Catapult fetches from
- `git_oauth_token_id` — reference to the stored OAuth
  credential
- `bundle_path` — relative path under `bundles/` to the
  active bundle (read from `catapult.yaml` at the project
  repo root; cached here for fast lookup)
- `created_at`

A project's bundle is declared at the project repo's
`catapult.yaml`. The Catapult server reads that file on
every fetch and updates the cached `bundle_path` if it
changed.

### A.9.2 Project creation

A new project is created via the dashboard:

1. User logs in.
2. User clicks "New project," provides name + description +
   a git remote URL.
3. User authorizes Catapult to access the git remote via
   GitHub OAuth (the same flow siege uses today).
4. Catapult fetches the repo, verifies it contains a
   `catapult.yaml` and a `bundles/<bundle>/` directory.
   If not, returns a typed error explaining what's missing.
5. On success, the project enters the user's project list.
   The user's first action is typically to start a CC
   session against the project and run `/scaffold`.

### A.9.3 Collaborators

The project owner can add **collaborators** via the
dashboard by entering their email or GitHub username.
Collaborators get read access: they see the project in
their dashboard, can browse the structured graph, can read
reviews, can clone the project repo locally via git. They
cannot drive the chain — calls to write tools from a
collaborator's JWT return `WriteAccessDenied`.

Collaborators are added one at a time; there are no teams,
no inherited memberships, no role hierarchy. A project
either has the owner as the only writer + zero or more
collaborators as readers, or has just the owner.

The owner can remove a collaborator at any time. Removal
is immediate; the collaborator's JWT continues to
authenticate but stops carrying access to the project.

### A.9.4 Credentials

Two credential types per project:

- **Owner's GitHub OAuth token.** Stored encrypted in
  Postgres, used by the server's git fetcher to clone and
  pull the project repo. Provided at project creation.
- **Per-user JWTs.** Issued by the dashboard's login flow.
  JWTs scope to the user identity; per-project access is
  checked at command time by looking up the user's role on
  the project.

There is no third credential type. The platform does not
manage SSH keys for repo access (the OAuth token covers
it), does not manage LLM API keys (CC manages its own auth
with Anthropic), and does not track LLM token usage
quotas (CC handles its own budget).

---

## A.10 Storage and code delivery

This chapter specifies the storage layout (git and
Postgres), the fetch semantics that move artifacts from CC's
local commits to Catapult's projections, and the
`git_commit` generator that delivers code from the chain
into a downstream code repository.

### A.10.1 Git: what's in the project repo

The project repo holds:

- **`catapult.yaml`** at the repo root — pins the active
  bundle directory.
- **`bundles/<name>/`** — bundle directories. Multiple
  bundles can coexist; the active one is named in
  `catapult.yaml`.
- **`<tier>/<scope_path>/body.md`** — per-scope body files.
  Path layout is bundle-declared per tier.
- **`<tier>/<scope_path>/review.md`** — per-scope review
  files where the scope has been reviewed.

That's the full surface. The repo contains no state files,
no identity ledgers, no propagation records, no phase plan,
no batches. All of that lives in Catapult's Postgres,
derived from the body files via the reducer.

The project's git history is the audit trail for body and
review changes. Catapult's event log is the audit trail for
status, approval, and structural changes. The two are
complementary; neither subsumes the other.

### A.10.2 Postgres: what Catapult stores

The event log + the projections from §A.3.3 + the entities
from §A.9 + the credentials from §A.9.4. No body content is
stored in Postgres; every read of a body's content goes via
a git fetch (typically cached per `(project_id, sha)`).

Postgres tables, summarized:

- **Event log:** `events`
- **Universal projections:** `nodes`, `edges`, `fragments`,
  `drafts`, `reviews`, `ready_scopes`, `staleness`, `flows`,
  `phase_plan`
- **Entities:** `users`, `projects`, `project_collaborators`,
  `lobby_holders`, `driver_sessions`
- **Credentials:** `oauth_tokens` (encrypted)
- **Snapshots:** `snapshots` (optional, per §A.3.6)

Per-bundle additions (tier-specific fragment kinds, etc.)
are JSON columns on the universal tables. No schema
migrations are required to load a new bundle.

### A.10.3 Fetch semantics

Whenever CC pushes a commit to the project's git remote and
calls a write tool with the new sha, Catapult's MCP handler
fetches the repo at that sha before running the command.
The fetch is debounced per `(project_id, sha)` — if two
write commands carry the same sha (because CC bundled work
into one commit), the second fetch is a cache hit.

Body and review file contents read during reducer + projection
update are read from the fetched blob, not from Postgres.
Postgres stores the sha only; the content is in the git
object store. This is what makes the body-in-git /
state-in-Postgres split a clean separation.

### A.10.4 The `git_commit` generator

Some tiers have content that isn't AI-generated prose —
they're the source code that the chain ultimately produces.
The platform recognizes a generator type `git_commit` for
this purpose:

A tier declared with `generator: git_commit` has its body
populated by reading a file from a downstream code
repository at a specific committed sha. The bundle declares:

- **`code_repo_url`** — the git remote for the code repo
  (distinct from the project's design repo where bodies
  live).
- **`path_from_handle`** — a Liquid expression evaluated
  against the tier's handle to produce the file path in
  the code repo.

When the agent commits source code to the code repo and
calls `commit_draft` with the new sha, the server fetches
the code file at that sha, reads its content into the body
projection, and runs the same lifecycle as any other tier.

This is how the default bundle's `code` tier (Part B §B.1)
materializes: subcomp implementations get drafted as design
prose first, then the user (via CC + a separate coding
agent) writes the actual code in a sibling repo, commits,
and Catapult reads the committed code into the code tier's
body.

### A.10.5 No code execution

Catapult never executes the code the chain produces. There
is no test runner, no build server, no sandbox, no CI
integration on the Catapult side. The code repo is a
downstream system; what runs against it is the user's
responsibility.

This is a deliberate scope choice. Catapult is a design
memory + reactive reactive-schema engine + agent driver;
running code is a different product entirely.

---

# Part B — Default bundle

The default bundle is Catapult's **graph-of-prompts design
system for AI code generation**. It takes a prose input
document describing a software project and produces a
layered structured model — features, responsibilities,
components, subcomponents, implementations — through a
reviewable pipeline that terminates in code committed to a
downstream repository.

The default bundle ships at `bundles/default/` in a new
project's repo, materialized at project creation by
Catapult's bootstrap routine. A user can edit it, fork it,
or replace it with a different bundle entirely; the
platform doesn't privilege the default.

This part specifies the default bundle's content. The
prompts that drive each tier's generation port from the
predecessor SiegeEngine's per-tier prompts (in siege's
codebase) to Liquid templates; the porting is part of the
bootstrap-handoff milestone (§B.2.7).

## B.1 Tier graph

The default bundle declares seven generation tiers, two
projection-only tiers, and a code-delivery tier. The chain
descends from extraction (reading the input doc) through
compression and rotation to leaves at implementation.

### B.1.1 The tier set

- **`feature_expansion`** — extraction tier. Reads the
  project's input document; produces a `<features>` list
  with each feature's name and intent prose. One scope per
  project; `scope: singleton`.
- **`requirements`** — rotation tier. Reads the features
  list; produces a list of system-level
  `<responsibility>` entries, each fulfilling one or more
  features. One scope per project; `scope: singleton`.
- **`sysarch`** — compression tier. Reads the
  responsibilities list; produces a top-level
  `<components>` list with each component's role,
  responsibilities, dependencies, domain-parent
  relationships, and project-level policy declarations.
  One scope per project; `scope: singleton`.
- **`comp`** — projection tier. Minted by sysarch's fanout;
  has no draft of its own. One scope per top-level
  component; `scope: child_of(sysarch)`.
- **`comparch`** — compression tier. Reads its comp's
  handle + the comp's fulfilled resp handles + the comp's
  dependencies' pubapi fragments; produces the comp's
  techspec, public/private API surfaces, policies, failure
  surface, and a subcomponent decomposition. Writes
  fragments on the comp via `produces:`. One scope per
  comp; `scope: per(comp)`.
- **`subcomp`** — projection tier. Minted by comparch's
  fanout. One scope per subcomponent.
- **`subcomparch`** — leaf articulation tier. Reads its
  subcomp's handle + its parent comp's handle + cross-
  subcomponent dependency handles; produces typed API
  signatures, internal design, and any subcomponent-local
  policies. One scope per subcomp.
- **`impl`** — design-of-implementation tier. Reads its
  subcomparch's handle + project-wide sysarch sections +
  related features; produces implementation prose ready for
  a coding agent to write code from. **Phased**: one body
  per `(subcomp, phase)` pair.
- **`fanin`** — synthesis tier. Aggregates a domain
  component's subcomponents' as-built handles; produces a
  bottom-up component-level summary that presentational
  consumers of the domain read. **Phased** + **`generator:
  synthesis`**. One scope per domain comp per phase.
- **`code`** — code delivery tier. `generator: git_commit`.
  Reads the impl handle; pulls actual source from a sibling
  code repo via the `git_commit` mechanism (§A.10.4). One
  scope per impl per phase.

Plus the platform-recognized `policy` tier (a node kind
sysarch fans out for project-wide policies; no draft of its
own, just a target for `policy_application` edges) and the
`vocab` tier (project glossary terms extracted during
feature_expansion).

### B.1.2 Foundation components

The default bundle's structural rule: every component
scope must have a `foundation` component as a structural
sibling. Foundation components hold cross-cutting
infrastructure (data persistence, logging, error reporting)
that other components depend on. The bundle declares
foundation as a `kind` value on the `comp` tier; sysarch's
fanout enforces "at least one foundation comp per project."

Foundation components have implications downstream:
foundation subcomparchs see their parent's policies +
techspec but not cross-component dependencies (because
foundation is leaf-most in the dependency graph), and
foundation impls run earliest in phase ordering.

### B.1.3 Domain vs presentational

Components carry a `kind` field: `domain` or
`presentational`. Domain components implement
domain-modeled responsibilities; presentational components
implement user-facing surfaces that consume domain
components via the `domain_parent` edge.

The fan-in tier synthesizes domain components' subcomp
handles bottom-up; presentational components' comparch
reads its domain parents' fan-in handles as context. This
is how the chain handles the
"presentational depends on as-built domain" pattern
without forcing top-down design of the presentational
surface upfront.

### B.1.4 Edge instances

The default bundle declares five edge instances against the
platform's edge types:

- **`fulfills`** — `type: reference`. From `comp` to `resp`,
  declared in `sysarch.draft.components[].responsibilities[].@id`.
  Cardinality: every resp is fulfilled by exactly one comp;
  every comp fulfills at least one resp.
- **`dependency`** — `type: dependency`. From `comp` to
  `comp` and from `subcomp` to `subcomp`. Declared in
  `comp.draft.dependencies[].@to` and
  `comparch.draft.sub_dependencies[]`. Graph constraint:
  `acyclic`, `no_self_loop`.
- **`domain_parent`** — `type: reference`. From
  presentational `comp` to one or more domain `comp`s.
  Declared in `sysarch.draft.components[].domain_parents[].@to`.
- **`decomposition`** — `type: fanout`. Cross-tier; emitted
  by sysarch (comp → resp via fulfills' inverse), by
  comparch (subcomp → resp via the per-subcomp `<owns>`
  block), and by feature_expansion (resp → feat via
  requirements' grammar).
- **`policy_application`** — `type: policy_application`.
  From `policy` to `comp` or `subcomp`. Declared in
  `sysarch.draft.policies[].applies_to[]` and
  `comparch.draft.policies[].applies_to[]`.

### B.1.5 Fragment kinds

The default bundle's fragment kinds:

- **`techspec`** — runtime, persistence, write-path,
  concurrency, testing, deploy, technologies. Owned by
  `comp` (project-wide; written by sysarch on the project's
  proj-comp scope) and by `subcomp` (component-level;
  written by comparch on each subcomp via `produces:`).
- **`pubapi`** — public API surface. Owned by `comp`
  (written by comparch) and by `subcomp` (written by
  subcomparch).
- **`privapi`** — private API surface. Owned by `subcomp`,
  written by subcomparch.
- **`policies`** — applied policies (component-level or
  subcomponent-level). Owned by `comp` and `subcomp`,
  written by the corresponding arch tier.
- **`failure_surface`** — failure mode catalogue. Owned by
  `comp` and `subcomp`, written by the corresponding arch
  tier.

Fragment kinds are a closed vocabulary in the bundle.
Adding a new kind is a bundle edit.

## B.2 Per-tier prompts

Each generation tier has a Liquid prompt template at
`prompts/<tier>.md.liquid` and (for reviewed tiers) a review
prompt at `prompts/review/<tier>.md.liquid`. The prompts
port verbatim from SiegeEngine's `siege/prompts/<tier>.md`
files — the prompts the legacy chain has been iterating on
since the start of the project.

### B.2.1 Port mechanics

The siege prompts today use Python f-string substitution
against a per-tier context dict (see CLAUDE.md's "per-tier
context bundles" section). The port to Liquid:

1. Replace each `{context_var}` with `{{ context_var }}`.
2. Replace each `{for x in xs:} ... {endfor}` (where siege
   uses informal loops) with `{% for x in xs %} ... {% endfor %}`.
3. Replace each `{if condition:} ... {endif}` with
   `{% if condition %} ... {% endif %}`.
4. Map siege's context-dict keys 1:1 to Liquid variables
   that the bundle's `context:` walks produce.

The semantics don't change. A prompt that produced a
sysarch body in siege today produces the same sysarch body
through Catapult's Liquid evaluation.

### B.2.2 Generation prompts

One Liquid template per generation tier:

- `prompts/feature_expansion.md.liquid`
- `prompts/requirements.md.liquid`
- `prompts/sysarch.md.liquid`
- `prompts/comparch.md.liquid`
- `prompts/subcomparch.md.liquid`
- `prompts/impl.md.liquid`
- `prompts/fanin.md.liquid`

Each renders against a Liquid context derived from the
tier's `context:` walks (§A.2.9). For example, comparch's
template receives `parent` (the comp handle), `fulfills`
(the comp's fulfilled resp handles), `dependencies` (the
comp's dependencies' pubapi fragments), `domain_parents`
(the comp's domain parents' synthesis handles where the
comp is presentational), and `prior_review` (when the
generation is a regen with prior review attached).

### B.2.3 Review prompts

One review template per reviewed tier:

- `prompts/review/feature_expansion.md.liquid`
- `prompts/review/requirements.md.liquid`
- `prompts/review/sysarch.md.liquid`
- `prompts/review/comparch.md.liquid`
- `prompts/review/subcomparch.md.liquid`
- `prompts/review/impl.md.liquid`
- `prompts/review/fanin.md.liquid`

Each review template receives the same Liquid context the
generation template did (since the reviewer must see what
the generator saw) plus `draft` (the body being reviewed).

### B.2.4 Thinking effort

The bundle declares per-tier `thinking_effort` on tiers
where deep reasoning improves output quality. The default
bundle assigns:

- `feature_expansion`, `requirements`, `sysarch` — max.
- `comparch` — max. Inline cross-section consistency,
  surface closure, dependency grounding, single-owner
  discipline — the comparch reconciliation pass is the
  most demanding generation in the chain.
- `subcomparch`, `impl`, `fanin`, review tiers — default.
  Late-stage compression doesn't need deep reasoning
  because the handles are already compressed.

The `thinking_effort` field is read by CC when it invokes
the LLM; the bundle declaration tells CC which budget to
assign per tier.

### B.2.5 The meaning-engine framing

The default bundle's prompts implement the meaning engine
described in `docs/architecture/v2-rearchitecture.md` (see
that document's "The system as a meaning engine" section).
Each tier produces compressed handles for the next; each
prompt names its downstream reader; each prompt pushes
against category-speak. Handle quality (meaning per token)
is what makes the chain work.

The meaning engine is a property of *these prompts*, not
of the platform. A different bundle could compose its tiers
differently — a bundle for visual design might produce
handles at finer granularity, a bundle for legal contracts
might produce different compression ratios. The platform is
generic over what handles mean.

### B.2.6 Per-tier context bundles

CLAUDE.md's "per-tier context bundles" section documents
the per-tier triad invariant the legacy chain enforces:
every generator and reviewer for the same tier consume the
same context dict. The Liquid port preserves this — the
generation and review templates for one tier receive
identical variables (plus `draft` on the review side), so
the reviewer sees the same context the generator saw.

This invariant is what makes the AI review catch drift
between intent (what the generator was supposed to do) and
output (what it did). Without it, reviewers would flag
"problems" that are just artifacts of the reviewer seeing
different context than the generator.

### B.2.7 Port milestone

The Liquid port is a bootstrap milestone, not an in-spec
artifact. SiegeEngine, when reading this spec to build
Catapult, materializes the Liquid templates by porting from
siege's existing Python-substituted markdown. The porting
is mechanical; the spec needs only the high-level mapping
(B.2.1) and the tier inventory (B.2.2 / B.2.3).

## B.3 Per-tier grammars

Each tier's body and review files conform to a grammar.
The grammars carry the structured fields downstream tiers
parse and the projection-derives fragments from.

### B.3.1 Body grammars

Body grammars are XML-fragmented markdown. The body file is
markdown prose with embedded structured `<element>` blocks.
The platform validates the embedded XML against an XSD
schema declared per tier; markdown text outside structured
elements is free prose.

Per-tier root tags:

- `feature_expansion` — `<features>` with one or more
  `<feature>` children, each with `<name>` and `<intent>`.
- `requirements` — `<requirements>` with one or more
  `<responsibility>` children, each with `<name>` and
  `<feats>` references back to feature IDs.
- `sysarch` — markdown sections (`## project_techspec`,
  `## project_policies`, etc.) plus `<components>`,
  `<policies>`, `<dependencies>`, and `<domain-parent>`
  blocks. The most structurally complex tier.
- `comparch` — markdown sections (`## comparch:techspec`,
  `## comparch:pubapi`, etc.) plus `<subcomponents>` and
  `<sub-dependencies>` and per-subcomponent `<owns>`
  blocks.
- `subcomparch` — markdown sections (`## subcomparch:pubapi`,
  `## subcomparch:privapi`, etc.) with typed signatures in
  XML.
- `impl` — markdown sections describing the implementation
  approach + structured `<types>`, `<functions>`, and
  `<tests>` blocks.
- `fanin` — markdown sections aggregating subcomp pubapis
  with structural caveats.

The XSDs and section conventions port from siege's
`backend/graph/parsers/validators.py` and
`backend/graph/parsers/xml_sections.py`. The port is
mechanical, not a redesign.

### B.3.2 Review grammar

Review files conform to a single platform-recognized
review grammar:

```xml
<review>
  <intro>One or two short paragraphs giving a "how close to
finished" read on the artifact.</intro>
  <score>0</score>
  <handles-structure>
    <finding id="h1">…</finding>
    …
  </handles-structure>
  <architectural-decisions>
    <finding id="a1">…</finding>
    …
  </architectural-decisions>
</review>
```

`<intro>` is 3-6 sentences of display-only prose.
`<score>` is an integer 0-100 with bucket semantics
(0-30: fundamental rework; 31-60: structural fixes; 61-85:
minor refinements; 86-100: ready). The two `<finding>`
sections are individually-addressable critiques the
dashboard renders as apply-as-feedback buttons.

The grammar is the same across every reviewed tier. Per-
tier review prompts ask the reviewer to fill the structure
with tier-appropriate findings.

### B.3.3 Validation at commit

When the agent commits a body or review file, Catapult's
write tool fetches the file at the new sha, runs the
bundle's per-tier grammar validator, and either accepts
the commit (reducer applies events) or rejects it (returns
a typed error CC can read and respond to). Validation is a
required gate; there is no "partially-committed" state.

## B.4 Per-tier readiness predicates

Each tier's `context:` walks define its readiness; the
default bundle's per-tier walks are:

- **`feature_expansion`** — `self.input_doc` (the project's
  input document, fetched from the project repo at a
  configured path). Ready as soon as the input doc exists.
- **`requirements`** — `self.upstream.feature_expansion →
  handle`. Ready when feature_expansion is approved.
- **`sysarch`** — `self.upstream.requirements → handle`.
  Ready when requirements is approved.
- **`comp`** — minted by sysarch fanout; readiness for the
  comp's downstream tiers depends on the comp existing in
  the projection.
- **`comparch`** — `self.parent.handle`,
  `self.parent.fulfills → resp.handle`,
  `self.parent.dependency → target.handle.fragments[pubapi]`,
  `self.parent.domain_parent → target.synthesis` (when
  parent is presentational). Ready when the comp exists +
  its fulfilled resps are approved + its dependencies' comparch
  pubapis are populated + its domain parents' fanins are
  populated.
- **`subcomp`** — minted by comparch fanout.
- **`subcomparch`** — `self.parent.handle`,
  `self.parent.parent.handle`,
  `self.parent.parent.dependency_of_subcomp → target.handle.fragments[pubapi]`.
  Ready when the subcomp exists, its comp's comparch is
  approved, and the subcomp's cross-subcomp deps within
  the comp are approved.
- **`impl`** — phased; for `(subcomp, phase)` pair: ready
  when subcomparch is approved, the phase's prior phases'
  impls for this subcomp are approved (if any), and the
  cross-phase context walk (§A.7.4) resolves.
- **`fanin`** — phased synthesis; for `(comp, phase)` pair:
  ready when every subcomp under the domain comp has an
  approved impl at this phase.
- **`code`** — `generator: git_commit`; ready signal is the
  bundle's commit-discovery mechanism (CC pushes code to
  the code repo and calls `commit_draft` with the code's
  sha).

These walks port from siege's per-tier readiness queries
(`siege/projection/`) into the bundle DSL.

## B.5 Phase rules

The default bundle's phase machinery declares which tiers
are phased and the plan rule that computes phase assignment.

### B.5.1 Phased tiers

Two tiers in the default bundle carry `phased: true`:

- `impl` — one body per `(subcomp, phase)` pair.
- `fanin` — one body per `(comp, phase)` pair (and only for
  domain comps).
- `code` — one body per `(impl, phase)` pair, mirroring
  impl.

All other tiers are unphased; each has one body per scope
regardless of phase.

### B.5.2 The plan rule

The default bundle's `plan_rule` (declared in
`bundles/default/plan.yaml`) computes phase assignment by:

1. **User-pinned feature phases** — the user assigns each
   approved feature to a phase via the dashboard. The
   default if not pinned is phase 1.
2. **Cascade up the chain** — each responsibility is
   assigned to the earliest phase any of its features are
   in. Each component to the earliest phase any of its
   responsibilities are in. Each subcomponent to the
   earliest phase its component is in. Each impl to the
   subcomponent's phase.
3. **Foundation overrides** — foundation components and
   their downstream impls are assigned to phase 1
   regardless of their responsibilities' phases. (Other
   components depend on foundation; foundation must build
   first.)
4. **Cross-component dependency** — a component depending
   on another component cannot be in an earlier phase.
   The plan rule rejects invalid assignments at compute
   time with a typed error.

### B.5.3 Plan recomputation

The plan recomputes whenever a body affecting assignment
changes — typically when sysarch is regenerated (component
set changed), comparch is regenerated (subcomponent set
changed), or the user re-pins a feature phase. The recompute
runs as part of the reducer's branch for the triggering
event; the new plan is written to the `phase_plan`
projection in the same transaction.

### B.5.4 Cross-phase delta context

Phased impl prompts receive a `prior_phases` Liquid
variable carrying the as-of-prior-phase impl handles for
the same subcomponent. The bundle's impl context walk
includes `self.subcomp → all_prior_phase_impls → handle`;
the platform's scope-resolution understands "all prior
phases" as iterating `phase` from 1 to (current_phase - 1).

The prompt incorporates the delta: "this impl is for phase
N; phases 1..N-1 produced these handles; build the next
slice that's consistent with them." Without the delta the
prompt would re-derive structural decisions on every phase
boundary.

## B.6 Flow definitions

The default bundle ships five flows. Each is declared as
`bundles/default/flows/<name>/flow.yaml` plus its prompt
files. Plus scaffolding, which is not a flow (§A.5.6).

### B.6.1 Scaffolding (baseline)

Walks the chain from input doc through every reviewed tier
in dependency order, drafting and reviewing each scope.
Driven by `/scaffold` in the agent's skill suite. Not a
flow; just the base schema running.

### B.6.2 Feature request

`bundles/default/flows/feature_request/`.

Seed: prose describing a desired feature change. Walk
primitive: `downward_cascade`. Adds a `feature_request_plan`
planning tier per scaffold tier the flow visits. The plan
tells the downstream regen what to change; the regen
incorporates it.

Used when the user wants to add a feature to an
already-scaffolded project: the flow walks down from
feature_expansion through every tier the new feature
implicates, regenerating each in the new state.

### B.6.3 Refactor

`bundles/default/flows/refactor/`.

Seed: prose describing a structural change (component
reshape, dependency reroute, responsibility redistribution).
Walk primitive: `downward_cascade`. Adds a `refactor_plan`
planning tier per visited scaffold tier.

Differs from feature_request in scope: refactor doesn't
add new functionality, it reshapes how existing
functionality is delivered. The plan grammar enforces
"this is a structural change, not a feature change"
discipline.

### B.6.4 Bug-fix propagation

`bundles/default/flows/bug_fix/`.

Seed: a defect report identifying a specific incorrect
behavior. Walk primitive: `downward_cascade`. Adds a
`bug_fix_plan` planning tier visiting the tier that
originated the defect plus the downstream tiers that need
to be regenerated to fix it.

### B.6.5 Downward propagation

`bundles/default/flows/downward_propagation/`.

Seed: a scope at which the user re-approved with changes
that need to propagate downstream. Walk primitive:
`downward_cascade`. Adds a `propagation_plan` planning tier
per visited downstream scope.

This is the explicit version of what staling does
implicitly. Used when the user wants to drive a propagation
with explicit per-scope plans rather than waiting for
ad-hoc regens to accumulate.

### B.6.6 Upward propagation

`bundles/default/flows/upward_propagation/`.

Seed: a scope at which a downstream argument (a comparch
flagging that its responsibilities are infeasible, a sub
comparch flagging that its parent's API surface is wrong)
suggests an upstream decision was wrong. Walk primitive:
`up_then_down`.

The walk goes upstream to the point at which a planning
decision needs to be made (typically requirements or
sysarch), generates a plan there, then propagates the
plan's effects back downstream.

### B.6.7 Plan-change flow

`bundles/default/flows/plan_change/`.

Seed: a phase plan diff (the user moved features between
phases, split a phase, dropped a phase). Walk primitive:
`downward_cascade` over the affected `(subcomp, phase)` and
`(comp, phase)` pairs. Regenerates phased impl + fanin
bodies whose phase assignments changed.

---

# Part C — Architecture

This part names the technologies that implement the platform
specified in Part A. Choices follow from Part A's commitments:
event-sourced state, reactive scheduler driven by pub/sub,
remote MCP transport, single-instance deployment per
Catapult instance. Each chapter explains the choice and what
it brings.

## C.1 Elixir / OTP

The application is built in Elixir on the BEAM. OTP
provides the concurrency primitives, supervision trees,
and fault-tolerance model that underpin the reactive
scheduler, the MCP server, and the dashboard.

The BEAM's soft-realtime scheduling is a good fit for
Catapult's workload: many concurrent lightweight processes
each handling one MCP connection or one projection update,
no thread-per-connection cost, hot code reloading for
operational convenience.

Supervision trees provide crash isolation by design: a
failed projection update doesn't take down the MCP server,
a crashed reducer branch doesn't take down the dashboard,
and reconciliation on startup rebuilds state from the event
log regardless of how the system came down.

## C.2 PostgreSQL

Primary data store for everything Catapult persists: event
log, projections (§A.3.3), entities (§A.9), credentials
(encrypted), optional snapshots. No second data store for
operational state — PostgreSQL is the single op store.

Migrations are forward-only. Downgrade raises. Schema
changes land with explicit Ecto migrations; the migration
history is the audit trail for "when did this column
enter the system."

Multi-column constraints PostgreSQL supports (partial unique
indexes, check constraints with subqueries) are used where
they encode real invariants — most notably the "at most one
pending draft per (project, node)" constraint.

The default deployment is a single PostgreSQL instance per
Catapult instance. Catapult does not multi-tenant the
database across instances; each Catapult deployment has
its own PostgreSQL.

## C.3 Commanded

The core domain uses Commanded for command/query
responsibility segregation and event sourcing.

Aggregates partition by project: each project's command
processing runs through a `Project` aggregate that owns the
invariants (single-pending-draft, lobby mutex, valid status
transitions). Commands fire through MCP write tools (§A.4.3);
events emit when the aggregate accepts; the reducer (a
Commanded event handler) applies events to projections.

Commanded gives Catapult:

- Complete audit trail of every action as the event log.
- Time travel and replay by running events 0..T against a
  fresh projection.
- Resumability: a partially-completed reducer pass picks up
  where it left off when the process restarts.
- Clean CQRS separation between commands (what happened) and
  queries (what state looks like).

The Commanded process manager facility is **not used for
the reactive scheduler** (per §A.3.4 and v3 §C.3.1's
treatment). The scheduler reacts to state, not events; the
Commanded event handler that broadcasts on Phoenix.PubSub is
all the engine borrows from Commanded for that path.

## C.4 Phoenix.PubSub and the reactive scheduler

`Phoenix.PubSub` provides the fast-path notification from
the reducer to the scheduler. The reducer broadcasts on a
per-project topic (`"project:<project_id>:committed"`) after
every successful transaction. The scheduler subscribes to
every project's topic on startup.

The scheduler is implemented as a `GenServer` per project,
each maintaining a small in-memory cache of the tier
declarations and edge instances from the loaded bundle.
On commit notification, the GenServer:

1. Reads the event payload to determine which tiers'
   readiness might have changed.
2. Re-evaluates context walks for the affected scopes.
3. Computes the new `ready_scopes` row diff.
4. Issues the inserts and deletes in a single Postgres
   transaction.

The sweeper runs as a separate process per project, ticking
every 30-60 seconds. It re-evaluates all enumerable scopes
regardless of recent events — the consistency floor.

PubSub topics are in-process for single-node deployments and
automatically distributed across a BEAM cluster if Catapult
is ever deployed multi-node. The current default is
single-node.

## C.5 Phoenix and LiveView

The dashboard is a Phoenix LiveView application. Server-
pushed state changes flow into the UI as reducer commits
broadcast — the LiveView pages subscribe to the same
per-project PubSub topics the scheduler does, and
re-render on each commit.

LiveView is a strong fit because Catapult's dashboard
exists to show state. There's no client-side workflow,
no offline-friendly editing — every interaction is
"read state, render, optionally fire a command back
through MCP or directly through an authenticated Phoenix
controller." LiveView's server-rendered model handles
this with much less complexity than a separate React app
talking to a backend.

Pages the dashboard exposes:

- **Project list** — the user's projects with read or
  write access.
- **Project workspace** — the graph view, the per-scope
  detail panel (body + review + history), the open-flow
  sidebar.
- **Review queue** — pending drafts awaiting human review.
- **Settings** — collaborator management, bundle switch,
  OAuth credential management.

## C.6 MCP server

The MCP server is an Elixir module exposing the read and
write tools from §A.4.2 and §A.4.3 over HTTPS. The
implementation:

- A Phoenix controller mounted at `/mcp/<project_id>` that
  handles MCP's JSON-RPC payload.
- Per-tool handler modules that translate MCP calls into
  either projection queries (read tools) or command
  dispatches at the project aggregate (write tools).
- JWT validation on every request; the per-project access
  check happens against the `project_collaborators` table.

The MCP transport is implemented from spec; there is no
mature Elixir MCP library at the time of writing. The
JSON-RPC + tool-discovery surface is small enough to hand-
write (a few hundred lines).

CC connects to the server with HTTP keep-alive; tool calls
are individual JSON-RPC requests over the connection.
Streaming responses are not required for the current tool
surface.

## C.7 Oban

Oban (a PostgreSQL-backed job queue for Elixir) handles
non-orchestration housekeeping:

- Event log compaction (older events to cold storage).
- Periodic projection rebuild for projects that haven't
  been touched recently (sanity check against event log).
- Snapshot maintenance (write a new snapshot every N
  events; prune snapshots older than the retention floor).
- Propagation-record cleanup for closed flows.
- OAuth token refresh.

Oban does **not** run the chain. There are no jobs that
call LLMs, no jobs that fire `commit_draft` on behalf of
CC, no jobs that drive flow progression. Workflow lives in
the agent, not in Oban.

## C.8 Git backend

A clone-per-project pattern: Catapult maintains a bare-ish
git clone of each project's repo under
`/var/lib/catapult/repos/<project_id>/`. On every
`commit_draft` or `commit_review` call, the server:

1. Acquires a per-project mutex on the clone.
2. Runs `git fetch origin <branch>` (debounced per
   `(project_id, sha)`).
3. Reads the body or review file via `git show
   <sha>:<path>`.
4. Releases the mutex.

The clone is the only place body content lives on
Catapult's side. Postgres stores the sha, never the body.

For the `git_commit` generator's downstream code repo,
Catapult maintains a separate clone per code-repo URL and
follows the same fetch pattern.

## C.9 libgraph

`libgraph` (Elixir graph library) handles the acyclicity
checks Catapult enforces:

- **At bundle-load time**, the type-level tier graph (tiers
  as nodes, edge instances as directed edges) is built and
  checked for cycles. A bundle with type-level cycles fails
  to load.
- **At projection time**, edges declared with
  `graph_constraint: acyclic` are validated per-instance.
  A `commit_draft` whose body would introduce a cycle in
  any acyclic edge instance is rejected.

libgraph's algorithms are well-tested; rolling Catapult's
own cycle detection would introduce bugs in a
correctness-critical path.

## C.10 Cytoscape with ELK

The dashboard's graph visualization uses Cytoscape.js with
the ELK layout extension. The graph view shows nodes
(scopes), edges (named instances), and (overlay) context-
walk dashed arrows for inspectability.

LiveView pushes node/edge data to Cytoscape via a small
LiveView hook; ELK computes layout client-side. Catapult
does not pre-layout the graph server-side.

## C.11 Observability

- **Telemetry.** Every reducer transaction, every scheduler
  re-evaluation, every MCP request emits a Telemetry event
  with project_id, command/tool name, duration, success or
  error.
- **Logging.** Structured logs with project_id and event
  sequence as standard fields.
- **Event log itself.** The event log is the audit trail
  for everything that changed; no separate audit log is
  needed.
- **Dashboard health page.** A LiveView page surfaces the
  Catapult instance's health: PostgreSQL connection pool,
  Oban queue length, scheduler ticker freshness per
  project, MCP active connection count.

External observability integrations (Prometheus,
OpenTelemetry, Datadog) are not part of v4; they can be
added later via Telemetry handlers without spec changes.

## C.12 The local Go CLI

The local CLI is a Go binary distributed via the bootstrap
script. Its job is narrow:

- **Bootstrap.** Install skills + the bundle into a new
  project repo; create `catapult.yaml`. Mirror of siege's
  `scripts/siege-bootstrap.sh`.
- **Pre-flight validation.** Parse + validate a body file
  against its tier grammar before commit. Saves a round-
  trip to the server on grammar errors. Runs entirely
  locally against a copy of the bundle's grammar files.
- **Local diagnostics.** "Does Catapult's projection match
  my local git state?" check, useful when something's
  gone weird.
- **Auth setup.** One-time flow that writes the Catapult
  MCP endpoint URL + JWT into a config file CC reads.

The CLI is a single static binary, ~1000-2000 LOC.
Distribution: GitHub releases plus a `brew install`-style
formula. The CLI binary speaks no MCP itself — CC handles
that directly with Catapult's remote server. The CLI is
just for the auxiliary local operations.

## C.13 Deployment

A Catapult instance runs as a single Docker container with:

- The Elixir release (Phoenix + Commanded + Oban + scheduler
  processes + MCP server + dashboard).
- A persistent volume for the bare-ish project clones.
- A PostgreSQL connection to a managed Postgres instance.

The default deployment is single-instance. Multi-node BEAM
clustering is possible but not the v4 target — single-node
is sufficient for the expected workload and removes a layer
of complexity.

CI/CD runs Catapult's own tests (the platform invariants,
the reducer's rebuild-from-zero correctness, the MCP tool
contract) on every PR; deploy runs on merge to main via
Docker build + push to the running instance.

## C.14 Licensing

AGPL-3.0-or-later. Same license SiegeEngine uses.
Forking the bundle is unrestricted; running Catapult as a
service requires source disclosure under the AGPL terms.
