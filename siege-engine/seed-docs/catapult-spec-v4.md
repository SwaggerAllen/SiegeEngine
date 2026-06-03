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
  Built-in scope expressions are `singleton`, `per(X)` (one
  per node of tier X), and `child_of(X)` (minted by X's
  fanout). A bundle may compose these — `per(comp) × phase`
  for a tier that's per-comp-per-phase — or declare custom
  scope expressions in a named-predicate escape hatch
  (§A.2.6).
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

**Named-predicate escape hatch.** A bundle that needs a
condition the six operator families can't express declares
a named predicate; the Catapult instance admin approves the
name at bundle import, and a per-instance allowlist maps
names to platform code. The name appears in the bundle as if
it were a built-in. The bundle itself contains no code. This
preserves the property "a bundle is learnable in an
afternoon" while allowing the rare case that genuinely needs
custom logic.

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
