# SiegeEngine v2 — Product Roadmap

Checkbox-driven roadmap from the event-sourced foundation through a
shippable MVP. Each phase is a vertical slice that lands behind an
approval gate and is demoable end-to-end before the next phase starts.

Authoritative scope: `docs/architecture/v2-rearchitecture.md` §MVP scope.
That doc is the "what" — this file is the "how, in what order, and
where are we."

Legend: `[x]` done · `[~]` in progress · `[ ]` not started

---

## Phase 0 — Foundation (data layer)

Landed on `main` as PR #290. Everything v2 writes goes through this.

- [x] Event log table + append-only writer (`GraphEvent`)
- [x] Reducer with one branch per event type (`backend/graph/reducer.py`)
- [x] Projections: `Node`, `Edge`, `Fragment`, `Draft`
- [x] Rebuild-from-log correctness test (incremental == replay)
- [x] Instruction vocabulary Pydantic models
- [x] Pending-change queue + `v2.apply_instructions` stub handler
- [x] Pipeline job queue with handler registry
- [x] Crockford base32 ID minting (`backend/graph/ids.py`)
- [x] Debug projection endpoint (`GET /api/projects/{id}/model`)
- [x] Alembic baseline migration `b1_v2_foundation`

## Phase 1 — Feature expansion (first vertical slice)

Landed on `claude/layered-dag-algorithms-llp3t`. Proves the foundation
holds end-to-end: events → reducer → projections → queue → handler →
routes → UI, with only the three new ingredients (LLM call site, one
prompt template, minimal approval UI).

- [x] `expansion` tier + migration `b2_expansion_tier`
- [x] `backend.graph.expansion` bootstrap/lookup helpers
- [x] `backend.graph.prompts.feature_expansion` prompt
- [x] `v2.generate_feature_expansion` job handler (regen discards prior pending)
- [x] `bootstrap + enqueue` on project creation
- [x] Four HTTP routes (`get / feedback / approve / discard`)
- [x] FastAPI lifespan wires the pipeline worker loop
- [x] React Query hooks + `FeatureExpansionPanel` with four visual states
- [x] Backend mypy clean, 149 v2 tests green, 7 component tests green

---

## Phase 2 — Feature-node minting from approved expansion

Turn the prose feature expansion into structured `feat_*` nodes. This
is where the structured model starts to replace the prose document as
source of truth.

- [ ] Prompt: parse approved expansion markdown → list of features (name + one-line intent)
- [ ] Generate-parse validation loop (retry on parse failure, escalate after N)
- [ ] On `DraftApproved` for the expansion node: enqueue `v2.mint_features` job
- [ ] Reducer / handler diffs against existing `feat_*` nodes — mint new, update renames, mark orphans for review
- [ ] Lineage preservation across re-approval (don't lose user edits to existing features)
- [ ] Routes: `GET /{project_id}/features`
- [ ] UI: feature list view on the dashboard under the approved expansion

## Phase 3 — Feature → Responsibility decomposition

Each feature decomposes into responsibilities. Many-to-many with
features, one-to-one up from component (later phase).

- [ ] `resp` tier already exists — add responsibility prompt
- [ ] Per-feature regeneration handler (prose draft + approval, reuse Phase 1 pattern)
- [ ] Structured UI #1: feature → responsibility drag-drop mapping page
- [ ] Prose instructions emitted from the drag-drop page (UI-as-prose-generator)
- [ ] Routes + hooks mirror the expansion pattern

## Phase 4 — Responsibility → Component mapping

- [ ] Component prompt (spec-level, not full arch doc yet)
- [ ] Structured UI #2: responsibility → component drag-drop mapping
- [ ] Approval flow mints / updates `comp_*` nodes

## Phase 5 — System architecture layer

The cold-start resolver: a top-level doc listing every component, its
API intent, and its dependency edges. Breaks the chicken-and-egg.

- [ ] New doc node kind at the system tier (or reuse existing `comp` tier with a system parent)
- [ ] Prompt: feature set + responsibilities + components → system architecture
- [ ] Parseable output: per-component API intent + dependency edges
- [ ] Reducer branches: `EdgeCreated` for `dependency` edges from parsed output
- [ ] Structured UI #5: dependency editor (Cytoscape) with cycle prevention (DFS from target to source)
- [ ] Approval gate: edits to system arch don't cascade until approved

## Phase 6 — Component architecture docs (parseable)

The biggest single chunk. This is where fragments and section-aware
propagation start paying off.

- [ ] XML section parser (`<public-surface>`, `<private-surface>`, `<dependencies>`, `<implementation>`)
- [ ] Generate-parse validation loop with retry-then-escalate
- [ ] Fragment extraction: on approval, split into `comp_X_pubapi`, `comp_X_privapi`, `comp_X_deps`
- [ ] `FragmentUpdated` event fires per changed fragment
- [ ] Component regen prompt in dependency topological order
- [ ] Prompt input scoping: parent doc + related features + `pubapi` fragments of deps (NOT full dep docs)
- [ ] Structured UI #3: component decomposition graph editor (Cytoscape)
- [ ] Tests: transclusion drift detection (system arch `pubapi` vs component arch `pubapi`)

## Phase 7 — Subcomponent recursion

Same shape as components, recursive.

- [ ] Recursive decomposition prompt and handler
- [ ] Subcomponent dependency scoping (same-parent siblings + parent's sibling components only)
- [ ] Structured UI #4: subresponsibility → subcomponent mapping
- [ ] Promotion / demotion instructions work across tiers without changing IDs

## Phase 8 — Presentational nodes + domain-parent edges

Unified DAG: domain and presentational share shape, distinguished by
`kind`. Presentational is strictly layered after domain.

- [ ] Presentational variants of feature / responsibility / component prompts
- [ ] `domain_parent` edge type already in the schema — add editor support
- [ ] Structured UI #6: domain-parent editor (same Cytoscape, different edge type / color)
- [ ] Regen prompt context for presentational: reads domain `pubapi` AND `domain-parent` sibling specs

## Phase 9 — Domain fan-in synthesis nodes

Bound the input set to presentational counterparts.

- [ ] Auto-mint one fan-in node per domain component with subcomponents
- [ ] Fan-in handler: reads all subcomponent implementations, writes a synthesis doc
- [ ] Feeds only the presentational counterpart via `domain_parent`
- [ ] Excluded from review scoping (mechanical, not user-editable)
- [ ] Staleness trigger: any subcomponent implementation change regenerates the fan-in

## Phase 10 — Implementation docs (leaves)

- [ ] `impl` tier leaf under component / subcomponent
- [ ] Implementation regen prompt (prose body, consumed whole by children)
- [ ] Approval gate per implementation

## Phase 11 — Section-aware diffs & bounded regen context

Formalize propagation. Everything after initial generation is diffs.

- [ ] Diff computation at fragment granularity (before/after `pubapi`, `privapi`, `deps`)
- [ ] Regen prompt helper: assemble parent doc + related features + dep `pubapi` fragments + neighbor diffs
- [ ] Staleness ledger: "this node is stale w.r.t. neighbor N at offset O"
- [ ] Crude fanout decision (MVP: regen all downstream; refinement is post-MVP)

## Phase 12 — Pending-change queue UX

The foundation already has the queue primitive. This phase is wiring
the six structured UIs into it.

- [ ] Every structured UI emits prose instructions, not direct writes
- [ ] Queue panel: list queued instructions, discard button (free undo)
- [ ] "Apply changes" button enqueues `v2.apply_instructions`
- [ ] Sequential execution invariant enforced (one job at a time, in submission order)
- [ ] Rename instructions rewrite prose via the LLM, not direct DB update

## Phase 13 — Batched review flow

Review pass = component. Combined navigable diff across every affected
node.

- [ ] `ViewRecorded` event is already in the vocabulary — use it
- [ ] Pin event offset on first review open per batch
- [ ] Point-in-time reconstruction via `rebuild_projections(up_to_offset=...)`
- [ ] Per-component review UI: walks pending nodes in topological order
- [ ] Fragment diff rendering (before/after side-by-side per fragment)
- [ ] Fan-in nodes skipped in review scoping
- [ ] Accept releases propagation to that node's downstream

## Phase 14 — Change summaries

- [ ] Every generation prompt appends a change-summary section
- [ ] Parser strips the summary from stored content, writes to a structured change log
- [ ] Queryable audit history endpoint
- [ ] Feeds into review UI (the summary is what gets shown as the diff header)

## Phase 15 — Code generation leaf pass

The bottom of the DAG: actual code.

- [ ] Per-project language setting (Catapult = Elixir)
- [ ] Code regen prompt: implementation doc + dep `pubapi` fragments + language conventions
- [ ] Language-specific validator (compile / typecheck hook) as parse-validate loop
- [ ] Retry-then-escalate on persistent failures
- [ ] Dependency topological execution order
- [ ] Generated code written to the project's git repo (v1 git plumbing survives)

## Phase 16 — Catapult smoke test

The acceptance test for v2. No migration from v1; rebuild from scratch.

- [ ] Load Catapult's input doc into a fresh v2 project
- [ ] Walk all 15 phases end-to-end, approving at each gate
- [ ] Verify generated Elixir compiles
- [ ] Capture feedback loop latency at each tier (is the 2s poll interval enough?)
- [ ] Identify which Phase-17 deferred items are actually blocking day-to-day use

---

## Post-MVP (deferred, tracked for awareness)

Per the architecture doc — nothing here is load-bearing for the first
shippable product.

- [ ] Fanout decision refinement (LLM-driven "which children actually changed")
- [ ] Vector search review augmentation
- [ ] Two-pass upward propagation automation
- [ ] Auto-propagation (explicit regen buttons work until regen quality is trusted)
- [ ] View-history snapshot optimization
- [ ] Multi-user concurrency on the pending-change queue
- [ ] WebSocket push instead of polling

---

## How to use this file

- Open a new phase by writing a plan under `/root/.claude/plans/` (same shape as `cheeky-soaring-token.md`) before coding.
- Flip `[ ]` → `[~]` when the plan is approved and work starts.
- Flip `[~]` → `[x]` only when the phase is merged and the acceptance test in the phase's own plan is green.
- Don't add new phases without updating the architecture doc's MVP scope section first. Scope creep dies here.
