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
