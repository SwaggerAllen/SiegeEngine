# SiegeEngine v3 architecture

Target architecture for the **substrate, data model, and execution
model**. v3 supersedes `v2-rearchitecture.md` for everything
execution-model-dependent. It does **not** re-derive the meaning-engine
design — the tier transformations, foundation components, policies,
vocabulary, and references in `v2-rearchitecture.md` were re-examined
and still hold; v3 references them rather than restating them. What
changed is the ground underneath: how artifacts are stored, how the
structured model exists, and what runs the chain.

## Why v3 is not a v2 amendment

`v2-rearchitecture.md` assumes an always-on backend that orchestrates
LLM jobs through a queue, an event-sourced SQL database, a reducer that
projects nodes / edges / fragments from an event log, and automatic
change propagation. The git migration deleted all of it. The execution
model that actually exists now:

- **Claude Code is the execution engine.** Skills compose artifacts;
  CC is the LLM; commands are the multi-step flows. No job queue, no
  worker, no LLM subprocess.
- **Git is the store.** Commits are the history; `git diff` is the
  diff; branches are parallel design exploration.
- **The `siege` core is a library, not a service.** Its read
  (projection) and write logic run locally via a CLI that Claude Code
  calls; a thin HTTP server exposes the read half to the dashboard.
  No job queue, no MCP transport.

Roughly 40% of v2 — the propagation engine, the reducer, the event log,
the job model — is obsolete by execution model alone. v3 is designed
around the model that exists, not patched onto the one that doesn't.

## Core principle

**Artifacts are the source of truth. The structured graph is a
projection of them. The only persisted state that is not an artifact
is the identity ledger and the propagation record.**

v2 inverted "documents are truth" to "the model is truth." That was
right in spirit and unbuildable on git — git holds files, not a node
graph. v3 keeps the spirit with a mechanism git can hold: the
LLM-authored documents are truth, and the node / edge graph is
*derived* from them deterministically. A projection cannot drift from
its source the way a denormalized cache can — and denormalized derived
state going stale is the failure mode the v2→git migration produced
everywhere it stored derived data.

## The three layers

### 1. Authored layer — git files

The truth. Hand-reviewed in the GitHub diff, written by CC skills.

- **`<tier>/<id>/body.md`** — the artifact: LLM-authored XML / prose.
- **`<tier>/<id>/review.md`** — the AI review of a draft.
- **`state/<tier>/<id>.json`** — lifecycle: status, draft / review /
  approval blocks, body sha, nonce, the upstream shas the draft was
  generated against.
- **`state/phases/<id>.json`, `state/cohorts/<id>.json`** — user
  planning intent (release phasing, iteration campaigns).

### 2. Core layer — the `siege` library

One library holds every deterministic operation over a project's git
tree — both the **projection** (read) and the **write** logic. Pure
functions; no long-lived state of its own.

Projection — given a git tree it computes:

- **the node / edge graph** — parse every approved body, resolve IDs
  against the identity ledgers, emit typed nodes and edges;
- **per-tier context bundles** — what each draft / review skill reads;
- **staleness** — which artifacts were generated against a now-stale
  upstream sha;
- **structure / review summaries** — the dashboard aggregations;
- **the graph-viz feed** — the `{nodes, edges}` shape the DAG views
  consume.

Write — given a freshly composed body it materializes the artifact:
compute the body sha, derive the identity ledger (assign / carry
forward IDs), write `state.json`, prepare the commit. The
deterministic half of every skill lives here, not in skill markdown.

It already does the projection half for *fragments*
(`parse_body_sections`). v3 generalizes that one good pattern:
**everything derived is parsed on read, never stored as truth.**

The library has two entry points — a local CLI (orchestration, §3)
and an HTTP server (the dashboard, below). Both are thin; all logic
is the library.

### 3. Orchestration layer — Claude Code + the core CLI

- **Skills** — one git commit each. A skill calls the core CLI for
  its context bundle, composes the artifact with the LLM (the only
  irreducibly-LLM step), calls the core CLI to materialize
  `body.md` + `state.json` + the identity ledger, then commits and
  pushes.
- **Commands** — the multi-step flows: `/scaffold`, `/run_tier`,
  `/regen_below`, `/status`.
- The core CLI runs **locally** in the Claude Code environment, so
  skills are network-independent — no server round-trip, works
  offline. There is **no MCP transport**.
- Precondition: the `siege` core is installed in the CC environment —
  pulled from GitHub, version-pinned to the project's state schema
  (see *On-ramp*). No dependency on the deployed host.

### The dashboard server

A thin, read-only HTTP wrapper over the core's projection, serving the
dashboard's views (graph, structure, review summaries). It is the only
long-lived process and the only network service; it caches the
projection per `(project, ref, sha)`. It is **not part of the
generation loop** — purely a viewer. If projection latency ever bites,
the escape hatch is to materialize `projection/graph.json` on commit;
the projection stays a pure function either way. Not built initially.

## Data model

- **Substrate file** — one git artifact = one draft → review → approve
  unit = one LLM generation pass = one `body.md`. Per-tier granularity
  (one feature_expansion per project, one comparch per component, …)
  tracks "what is co-generated" and is correct as-is.
- **Node** — a graph entity (`feat_ / resp_ / comp_ / impl_ / policy_`
  …). Persisted: **only its stable ID**. Everything else — name,
  content, kind, order — is projected from the substrate body that
  declares it.
- **Edge** — a typed relation. The edge-type vocabulary
  (`decomposition`, `dependency`, `domain_parent`, `policy_application`,
  `reference`) is inherited from `v2-rearchitecture.md` §Edge type
  vocabulary. Edges are **fully projected** from bodies; never stored.
  How the comparch `<owns>` block projects (ownership edges vs. node
  attribution) is settled in the projection-layer design.
- **Identity ledger** — `ids/<tier>/<id>.json`, **one per substrate**.
  A persisted derived artifact: `{node_id ↔ name / alias}` for every
  node the substrate declares, plus the body sha it was derived
  against. It exists so IDs survive regeneration — a renamed body
  element keeps its ID by name-match against the ledger. It stores
  **identity only**; node content stays projected.
- **Propagation record** — `state/propagations/<id>.json`. A tracked
  worklist (see *Propagation*).

A substrate declares 1..N nodes. Some declared nodes are also the root
of a substrate at the next tier (a `comp_*` node ↔ a comparch
substrate). That mapping is a fixed per-tier fact, not data.

## Storage layout

```
<tier>/<id>/body.md                  authored artifact
<tier>/<id>/review.md                AI review
state/<tier>/<id>.json               lifecycle
ids/<tier>/<id>.json                 identity ledger (decomposing tiers only)
state/propagations/<id>.json         tracked propagation
state/phases/<id>.json               release phasing
state/cohorts/<id>.json              iteration campaigns
```

Phased impl / fanin keep the `p<N>` path layout from the state schema.

## The tier chain

| tier | substrate granularity | transform | declares nodes | projects |
|------|----------------------|-----------|----------------|----------|
| feature_expansion | 1 / project | extraction | `feat_*` | — |
| requirements | 1 / project | rotation | `resp_*` | `decomposition` feat→resp |
| sysarch | 1 / project | compression | `comp_*` (top-level), `policy_*` | `dependency`, `domain_parent` |
| comparch | 1 / component | compression | `comp_*` (subcomponent), `policy_*` | `dependency` (sub), `<owns>` resp/feat claims |
| subcomparch | 1 / subcomponent | leaf articulation | — | — |
| impl | 1 / leaf, phased | implementation | — | — |
| fanin | 1 / domain comp w/ subs, phased | bottom-up synthesis | — | — |
| plan *(future)* | 1 / impl | code-change planning | — | — |

The four **decomposing tiers** — feature_expansion, requirements,
sysarch, comparch — declare child nodes and therefore carry identity
ledgers. The leaf tiers do not. Tier transformation semantics (why
each is compression / rotation / expansion, the handle-quality
property) carry over unchanged from `v2-rearchitecture.md` §The system
as a meaning engine.

## Phasing and code generation

**Phasing.** impl and fanin partition across release phases; the five
arch tiers never do. The phase registry (`state/phases/`) is
user-authored release intent. The per-phase build order is a
**projection** — `compute_plan` derives it from the registry + the
comparch / subcomparch tiers, computed on read, not stored as truth.
Creating the per-phase impl scopes from that plan is the impl fanout —
the same shape as comparch → subcomparch.

**`plan` and `code` are designed, not implemented.** The per-impl
`plan_*` node (translate an impl edit into a concrete code-change
list — `v2-rearchitecture.md` §Plan nodes) and the final `code`
generation pass are part of the designed chain — the tier table lists
`plan` for completeness — but neither exists in the current code. v3
carries them as future tiers; they slot below impl as leaf tiers, no
new substrate concept. The `plan_*` node is unrelated to the phasing
`compute_plan` above — they share only the word.

## Lifecycle

Each substrate moves `absent → drafted → reviewed → approved`, one git
commit per transition, via the per-tier skills. Within a draft:

1. The skill calls the core CLI for the scope's context bundle.
2. The LLM composes the body; the CLI validates it.
3. The skill calls the core CLI to materialize `body.md` +
   `state.json`, and — for a decomposing tier — the identity ledger:
   parse the body's declared elements, carry IDs forward from the
   prior ledger by name, mint fresh IDs for new names.
4. One commit; push.

**Leaf tiers read a seed they never store.** subcomparch and impl
declare no child nodes — so no identity ledger — but each *consumes*
its slice of the parent comparch's `<owns>` block (its `parent_resps`
+ feat-slice). That seed is assembled into the context bundle by the
projection in step 1, read from the parent comparch's ledger + body;
it is never copied into the leaf's own state.

**fanin is the one lifecycle exception.** A fan-in node is mechanical
bottom-up synthesis — recomputed per phase, never hand-iterated: per
v2 it is *not reviewed directly* because real corrections land at the
subcomponent impls below it. Whether v3 keeps a review step for fanin
at all is unresolved — the current skill set ships `review-fanin`;
see *Open questions*.

**There are no mint handlers and no fanout handlers.** A node exists
the moment a body declares it — there is nothing to mint into being.
The only persisted act at a tier boundary is ID assignment (step 3).
The next tier's substrates are created by their own draft skill; the
orchestrator enumerates them from the projected graph. v2's "approve
to mint" becomes "approve the body" — the draft → review → approve
gate on the body *is* the review-the-decomposition gate.

## Propagation

**Staleness is a projection.** An artifact is stale when an upstream
artifact it was generated against has a newer approved sha.
`state.json` records the upstream shas a draft was generated against;
the projection compares them to current.

**A propagation is a tracked record.** When an approved change creates
downstream staleness, a `propagation` record snapshots the stale set
as a **worklist** — each entry a `(scope, status)` pair — written to
`state/propagations/`. As each downstream node is regenerated, the
regen / approve skill updates its worklist entry. The record is the
memory of "what still needs regen," so the flow never depends on the
user remembering which nodes are done and which are waiting.

Today the worklist is **drained manually** — `/regen_below` opens a
propagation, `/status` shows progress, the user works the list. A
future `/propagation-loop` command (a CC `loop`) drains it
automatically. The record is identical for both; only the driver
changes. Propagation records build on the existing batch primitive
(resume-by-gap-fill).

**Cross-tree hops propagate too.** Most staleness runs down the tier
chain, but two edges cross it: a fan-in node recomputes when any impl
beneath it changes, and — because fan-in feeds a presentational
component through its `domain_parent` edge — a fan-in update makes
that presentational comparch stale. A propagation worklist includes
those cross-tree targets like any other.

## Identity and the alias scheme

Decomposing-tier bodies refer to not-yet-identified children by
**alias** (`<subcomponent alias="session_store">`) — generation-time
handles, so the LLM never juggles opaque IDs. The **identity ledger**
assigns the stable `<kind>_<suffix>` ID, post-draft, by name / alias
match. Aliases stay in the body for local cross-references; the ledger
holds alias→id. This is not debt — it is the design: alias is the
authoring form, the ID is the identity form, the ledger bridges them.

## Orchestration surface

**Core CLI** — the deterministic operations a skill needs: read a
context bundle, validate a candidate body, materialize `body.md` +
`state.json` + identity ledger. Replaces the inline `python3` heredocs
skill markdown carries today.

**Skills** (one commit each): `draft-*`, `review-*`,
`regen-*-with-feedback`, `mark-{drafted,reviewed,approved}`,
`repair-state-drift`. Each is thin orchestration — call the CLI,
compose with the LLM, call the CLI, commit.

**Commands** (flows): `/scaffold`, `/run_tier`, `/regen_below`,
`/status`, `/continue`.

**Future commands** — designed for, not built initially. Each is
expressible as orchestration commands + projection queries; none needs
a new substrate concept:

- `/feature-request`, `/refactor`, `/bug-fix` — the three
  non-scaffolding change flows; each is an upstream edit + a
  propagation.
- `/propagation-loop` — auto-drains a propagation record.
- bundle configuration, phase-zero machinery — additional planning
  artifacts alongside phases / cohorts.

## On-ramp

The generate loop has **no dependency on the deployed host.**
Everything it needs is pulled from the GitHub repo:

- **the `siege` core** — `pip install` from the repo, with a tag or
  sha pinning the version against the project's state schema;
- **skills + commands** — Claude Code's native plugin install from
  the same repo, or a repo-resident setup script for environments
  without plugin install.

The deployed droplet serves only the dashboard. There is no
`bootstrap.sh` endpoint — onboarding a project is a GitHub pull, so
the loop keeps working whether or not the dashboard host is up.

## What v3 drops from v2 (and why)

- **Event-sourced reducer + event log** — git history is the log.
- **Node / Edge / Fragment SQL tables** — the graph is projected.
- **Job queue + worker + LLM subprocess** — CC is the engine.
- **Mint / fanout handlers** — nodes are projected, not minted.
- **Stored staleness ledger** — staleness is a projection.
- **Autonomous propagation engine** — replaced by the propagation
  record + manual drain (auto-drain loop later).
- **`state.edges`** — the per-file edge dict; edges are projected.
- **The MCP / JSON-RPC transport** — skills call the core CLI
  locally; the dashboard uses plain HTTP. `siege_mcp` is renamed
  `siege`; the "MCP" was never load-bearing.

## What v3 keeps from v2

Re-examined and still correct — referenced, not restated:

- the meaning-engine treatment (tier transformations, handle quality);
- foundation components and the no-nesting rule;
- the policy model (capability ownership vs. enforced usage);
- vocabulary (`vocab_*`) and references (`ref_*`);
- fragments as addressable transcluded sections — projected on read
  in v3;
- the file-territory manifest (`manifest_*`) for code generation —
  unrelated to the identity ledger; the v3 ledger deliberately does
  **not** reuse the word "manifest".

## Migration path

From the current code to v3, in order:

1. **Consolidate the core — done.** `siege_mcp` renamed to `siege`;
   the read side gathered under a `siege/projection/` subpackage (the
   per-tier context builders + `structure` / `review_summary` /
   `plan`); `cli.py` kept as the write half. Behavior-preserving —
   the test suite passed unchanged.
2. **Move write logic out of skill markdown — done.** Every
   write-side skill calls `siege` CLI subcommands instead of carrying
   an inline `python3` heredoc; the CLI is the behavior-identical
   superset (state JSON, node manifests, sha/nonce, lenient review
   parse). The package is `pip install`-able with the runtime deps
   split into an `[app]` extra so the core install is dependency-free,
   and the bootstrap script installs the `siege` core, version-pinned.
   Behavior-preserving — byte-diffed against the retired heredocs.
3. **Identity ledger — slim + rename done.** The node manifest is now
   the slim identity ledger at `ids/<tier>/<id>.json`: each node
   persists only its `id` + `name`; the projectable fields (`kind` /
   `order` / `intent` / `implicit` / `feats`) are re-derived from the
   body and rehydrated by the projection on read. The reader still
   accepts the legacy v1 fat manifest, so a `manifest/` tree migrates
   with a plain `git mv`. Extending the ledger to sysarch + comparch
   folds into step 4.
4. **ID assignment at the decomposing tiers — done.** The identity
   ledger now covers `sysarch` (declares `comp_*` components) and
   `comparch` (declares `comp_*` subcomponents); `derive_manifest`
   mints and carries those ids forward by the `alias` attribute,
   folded into the `draft-sysarch` / `draft-comparch` CLI write path.
   The `siege.cli list-scopes` subcommand enumerates the comparch /
   subcomparch scope set from the ledgers and `/run_tier` fans out the
   chain from it — closing the sysarch→comparch and
   comparch→subcomparch fanout gaps. Edge resolution (`<dependencies>`
   alias→id) stays projection work; `policy_*` nodes are deferred.
5. **Skills read context from the CLI**, not an MCP tool. Drop the
   MCP / JSON-RPC transport, the plugin's `.mcp.json`, and the
   deployed `bootstrap.sh` endpoint; the on-ramp becomes a GitHub
   pull (see *On-ramp*).
6. **Repoint the graph viz** from the legacy backend's `/structure`
   endpoint to the dashboard server's projection endpoint.
7. **Propagation records.** `/regen_below` writes one; `/status`
   reads it.
8. **Cleanup.** Delete `state.edges` and the vestigial multi-node
   readers; then the deferred legacy-backend deletion can run.

## Open questions

- The propagation worklist is snapshotted at creation — if upstream
  changes again mid-drain, does the record extend or does a second
  record open? (Lean: extend.)
- Projection materialization trigger, if lazy per-sha caching proves
  too slow.
- Whether `subcomparch` should carry a lightweight identity ledger for
  symmetry even though it declares no child nodes. (Lean: no.)
- Whether `fanin` carries a review step at all — v2 says fan-in is not
  reviewed directly, but the current skills ship `review-fanin`.
