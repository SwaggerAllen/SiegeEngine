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

## Phase 2 — Feature minting from approved expansion

Turn the prose feature expansion into structured `feat_*` nodes.
Features are user intent, not architecture — they fall out of the
expansion naturally as a bulleted list, and the feature list is a
user-facing artifact independent of components.

- [ ] Prompt: parse approved expansion markdown → list of features (name + one-line intent)
- [ ] Generate-parse validation loop (retry on parse failure, escalate after N)
- [ ] On `DraftApproved` for the expansion node: enqueue `v2.mint_features` job
- [ ] Diff against existing `feat_*` nodes — mint new, update renames, mark orphans for review
- [ ] Lineage preservation across re-approval (don't lose user edits to existing features)
- [ ] Routes: `GET /{project_id}/features`
- [ ] UI: feature list view on the dashboard under the approved expansion

## Phase 3 — System architecture (one-shot)

The cold-start resolver. **One LLM call** with the full feature set in
context produces the whole component graph in a single coherent
artifact: responsibilities, components, their dependency edges, their
domain-parent edges, and each component's API intent. Iterated on as
a prose doc with feedback, same gate as the expansion.

This is one phase, not four, because **dependencies and responsibility
assignment are global decisions** — you cannot decide "component A
depends on component B" from inside feature F's decomposition (B might
not exist yet), and a responsibility that looks like it belongs to F
might actually be shared with G. Per-feature decomposition loses the
architect's "how does this all fit together" view, and extract-as-new-
component — the most common cross-cutting answer — requires >1 feature
in context at once.

- [ ] New `sysarch` tier node minted once per project (similar bootstrap to expansion)
- [ ] Prompt: approved feature set + (optional) prior approved sysarch + feedback → single prose system architecture doc
- [ ] Parseable output sections per component: API intent, responsibilities covered, dependency list, domain-parent list
- [ ] Generate-parse validation loop (retry-then-escalate) — sysarch output is load-bearing for everything downstream
- [ ] Handler reuses Phase 1's flow (draft → approve → commit)
- [ ] On `DraftApproved` for the sysarch node: parse structured output and emit:
  - [ ] `NodeCreated` for each new `resp_*`
  - [ ] `NodeCreated` for each new `comp_*` (with API intent stored as the `pubapi` fragment)
  - [ ] `EdgeCreated` for each `dependency` edge
  - [ ] `EdgeCreated` for each `domain_parent` edge
  - [ ] Diff against existing resp / comp / edges — preserve lineage, mark orphans
- [ ] Cycle prevention on dependency edges (DFS from target to source) inside the parser — reject the whole parse on a cycle and loop back to regen with the error
- [ ] Routes mirror expansion (`get / feedback / approve / discard`) for the sysarch node
- [ ] UI: read-only system architecture view with the expansion-style four-state panel

**Structured edit UIs for feat↔resp, resp↔comp, and dependency / domain-parent edges are NOT part of this phase.** They're layered on top of the minted structure in Phase 12 — every structured UI is a prose-instruction generator feeding the pending-change queue, not a separate generation step.

## Phase 4 — Component architecture docs (parseable)

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

## Phase 5 — Subcomponent recursion

Same shape as components, recursive.

- [ ] Recursive decomposition prompt and handler
- [ ] Subcomponent dependency scoping (same-parent siblings + parent's sibling components only)
- [ ] Structured UI #4: subresponsibility → subcomponent mapping
- [ ] Promotion / demotion instructions work across tiers without changing IDs

## Phase 6 — Presentational nodes + domain-parent edges

Unified DAG: domain and presentational share shape, distinguished by
`kind`. Presentational is strictly layered after domain.

- [ ] Presentational variants of feature / responsibility / component prompts
- [ ] `domain_parent` edge type already in the schema — add editor support
- [ ] Structured UI #6: domain-parent editor (same Cytoscape, different edge type / color)
- [ ] Regen prompt context for presentational: reads domain `pubapi` AND `domain-parent` sibling specs

## Phase 7 — Domain fan-in synthesis nodes

Bound the input set to presentational counterparts.

- [ ] Auto-mint one fan-in node per domain component with subcomponents
- [ ] Fan-in handler: reads all subcomponent implementations, writes a synthesis doc
- [ ] Feeds only the presentational counterpart via `domain_parent`
- [ ] Excluded from review scoping (mechanical, not user-editable)
- [ ] Staleness trigger: any subcomponent implementation change regenerates the fan-in

## Phase 8 — Implementation docs (leaves)

- [ ] `impl` tier leaf under component / subcomponent
- [ ] Implementation regen prompt (prose body, consumed whole by children)
- [ ] Approval gate per implementation

## Phase 9 — Section-aware diffs & bounded regen context

Formalize propagation. Everything after initial generation is diffs.

- [ ] Diff computation at fragment granularity (before/after `pubapi`, `privapi`, `deps`)
- [ ] Regen prompt helper: assemble parent doc + related features + dep `pubapi` fragments + neighbor diffs
- [ ] Staleness ledger: "this node is stale w.r.t. neighbor N at offset O"
- [ ] Crude fanout decision (MVP: regen all downstream; refinement is post-MVP)

## Phase 10 — Pending-change queue UX + structured edit UIs

The foundation already has the queue primitive. This phase is building
all six structured edit UIs on top of the minted model from Phases 3
and 4, and wiring them into the pending-change queue. **No UI mutates
the model directly — every action produces prose instructions.**

- [ ] Queue panel: list queued instructions, discard button (free undo), "Apply changes" button
- [ ] "Apply" enqueues a single `v2.apply_instructions` job; sequential execution invariant
- [ ] Rename instructions rewrite prose via the LLM, not direct DB update
- [ ] Structured UI #1: feature → responsibility mapping (drag-drop, assign-only)
- [ ] Structured UI #2: responsibility → component mapping (drag-drop, assign-only)
- [ ] Structured UI #3: component / subcomponent decomposition (Cytoscape, create/move/delete)
- [ ] Structured UI #4: subresponsibility → subcomponent mapping (drag-drop)
- [ ] Structured UI #5: dependency editor (Cytoscape, with cycle prevention)
- [ ] Structured UI #6: domain-parent editor (same Cytoscape, different edge type / color)
- [ ] Mobile interaction: tap-to-select + tap-to-place for drag-drop, tap-two-nodes for graph editors
- [ ] All six UIs support promotion / demotion between tiers without changing IDs

## Phase 11 — Batched review flow

Review pass = component. Combined navigable diff across every affected
node.

- [ ] `ViewRecorded` event is already in the vocabulary — use it
- [ ] Pin event offset on first review open per batch
- [ ] Point-in-time reconstruction via `rebuild_projections(up_to_offset=...)`
- [ ] Per-component review UI: walks pending nodes in topological order
- [ ] Fragment diff rendering (before/after side-by-side per fragment)
- [ ] Fan-in nodes skipped in review scoping
- [ ] Accept releases propagation to that node's downstream

## Phase 12 — Change summaries

- [ ] Every generation prompt appends a change-summary section
- [ ] Parser strips the summary from stored content, writes to a structured change log
- [ ] Queryable audit history endpoint
- [ ] Feeds into review UI (the summary is what gets shown as the diff header)

## Phase 13 — Code generation leaf pass

The bottom of the DAG: actual code.

- [ ] Per-project language setting (Catapult = Elixir)
- [ ] Code regen prompt: implementation doc + dep `pubapi` fragments + language conventions
- [ ] Language-specific validator (compile / typecheck hook) as parse-validate loop
- [ ] Retry-then-escalate on persistent failures
- [ ] Dependency topological execution order
- [ ] Generated code written to the project's git repo (v1 git plumbing survives)

## Phase 14 — Catapult smoke test

The acceptance test for v2. No migration from v1; rebuild from scratch.

- [ ] Load Catapult's input doc into a fresh v2 project
- [ ] Walk all 13 phases end-to-end, approving at each gate
- [ ] Verify generated Elixir compiles
- [ ] Capture feedback loop latency at each tier (is the 2s poll interval enough?)
- [ ] Identify which post-MVP deferred items are actually blocking day-to-day use

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
