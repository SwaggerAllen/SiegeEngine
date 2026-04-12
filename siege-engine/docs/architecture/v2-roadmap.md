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
- [ ] **Generation telemetry plumbed from first real LLM call.** Wrap the LLM client so every call records `(node_id, fragment_or_section, model, prompt_tokens, completion_tokens, timestamp)` to a side table. Surface in the UI on every node that has ever been generated: latest token count shown in-place, not behind a button. Cheap to add now, expensive to retrofit.

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

## Phase 3 — System architecture (two-pass singleton)

The cold-start resolver. A singleton `sysarch` node generated in two
passes, same gate model as the expansion. Pass A is local reasoning
(features → responsibilities), Pass B is global reasoning
(responsibilities → components + APIs + dep edges + domain-parent
edges + system-level techspec in one call).

Why two passes and not four, and why not one: component boundaries
are justified by the APIs they expose and the dep edges they avoid,
so components + APIs + edges have to be reasoned about jointly or
you get boundaries that don't hold up to their own API decisions.
But features → responsibilities is local and low-risk, so splitting
it off gives a cheap review checkpoint without costing joint
reasoning on the parts that need it.

- [ ] New singleton `sysarch` tier node minted once per project (similar bootstrap to expansion)
- [ ] Cold-start vs incremental-add are distinct prompt templates (one job handler picks which)
- [ ] **Pass A prompt:** approved feature set → responsibilities-only section of sysarch doc
- [ ] **Pass B prompt:** approved pass A output + features → full sysarch (components, APIs, dep edges, domain-parent edges, system `techspec`)
- [ ] Pass B consumes pass A's approved output; pass A must be approved before pass B runs
- [ ] Parseable output sections: system `techspec`, responsibilities, per-component (API intent, responsibilities covered, dependency list, domain-parent list)
- [ ] Generate-parse validation loop (retry-then-escalate) — sysarch output is load-bearing for everything downstream
- [ ] Handler reuses Phase 1's flow (draft → approve → commit), extended to two sequential passes
- [ ] On `DraftApproved` for the sysarch node (after pass B): parse structured output and emit:
  - [ ] `NodeCreated` for each new `resp_*`
  - [ ] `NodeCreated` for each new `comp_*` (with API intent stored as the `pubapi` fragment and techspec as `techspec` fragment)
  - [ ] `EdgeCreated` for each `dependency` edge
  - [ ] `EdgeCreated` for each `domain_parent` edge
  - [ ] Diff against existing resp / comp / edges — preserve lineage, mark orphans
- [ ] Cycle prevention on dependency edges (DFS from target to source) inside the parser — reject the whole parse on a cycle and loop back to regen with the error
- [ ] Initial mint is treated as destructive at the child level (gated on explicit approval); subsequent edits to minted children propagate normally
- [ ] Routes mirror expansion (`get / feedback / approve / discard`) for both passes of the sysarch node
- [ ] UI: read-only system architecture view with the expansion-style four-state panel, aware of which pass the node is in

**Structured edit UIs for feat↔resp, resp↔comp, and dependency / domain-parent edges are NOT part of this phase.** They're layered on top of the minted structure in Phase 10 — every structured UI is a prose-instruction generator feeding the pending-change queue, not a separate generation step.

## Phase 4 — Component architecture docs (parseable)

The biggest single chunk. This is where fragments and section-aware
propagation start paying off, and this is also where the shared
diff-aware regen helper lands — built as a primitive from the start,
not retrofitted later.

- [ ] XML section parser (`<technical-specification>`, `<public-surface>`, `<private-surface>`, `<dependencies>`)
- [ ] Generate-parse validation loop with retry-then-escalate
- [ ] Fragment extraction: on approval, split into `comp_X_techspec`, `comp_X_pubapi`, `comp_X_privapi`, `comp_X_deps`
- [ ] Fragment kinds validated as single-token at parser boundary
- [ ] `FragmentUpdated` event fires per changed fragment
- [ ] **Shared regen-prompt assembly helper** — one module used by every tier's regen: parent doc + related features + dep `pubapi` fragments + neighbor diffs. Phases 5/6/7/8 reuse it rather than reimplementing.
- [ ] Fragment-level diff computation (before/after per fragment) lands here, not in a later consolidation phase
- [ ] Component regen prompt in dependency topological order, via the shared helper
- [ ] Prompt input scoping: parent `techspec` + related features + `pubapi` fragments of deps (NOT full dep docs)
- [ ] Techspec propagates downward only; child impl changes do not regenerate parent techspec
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

- [ ] Auto-mint one fan-in node (`fanin_*`) per domain component with subcomponents, **unconditionally** — minted whether or not a presentational counterpart currently exists, so adding a domain-parent edge later is a pure edit, not a mint-on-the-fly
- [ ] Fan-in handler: reads all subcomponent implementation nodes, writes a synthesis doc
- [ ] Feeds presentational counterparts (current or future) via `domain_parent`
- [ ] Excluded from review scoping (mechanical, not user-editable)
- [ ] Staleness trigger: any subcomponent implementation change regenerates the fan-in

## Phase 8 — Implementation nodes (leaves)

Implementation nodes (`impl_*`) are separate leaf nodes, distinct from
the parent component's `<technical-specification>` section. One impl
node per subcomponent and per un-fanned-out component.

- [ ] `impl` tier node minted as leaf under each subcomponent and each un-fanned-out component
- [ ] Components with subcomponents have no impl node of their own — their impl lives in their subcomponents' impl nodes
- [ ] Implementation regen prompt: parent `techspec` + parent `pubapi`/`privapi` fragments + dep `pubapi` fragments
- [ ] Uses shared regen helper from Phase 4
- [ ] Destructive-edit gate only; non-destructive impl edits propagate automatically to plan nodes

## Phase 9 — Staleness ledger & fanout decision

The diff helper and fragment-level diffs already landed in Phase 4.
What remains for propagation is the bookkeeping layer that decides
*what* to regen next.

- [ ] Staleness ledger: "this node is stale w.r.t. neighbor N at offset O"
- [ ] Crude fanout decision (MVP: regen all downstream; refinement is post-MVP)
- [ ] Wire the destructive-op gate into the fanout decision — destructive edits halt the cascade, non-destructive edits flow through

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

Review pass = component. MVP ships a simple per-component walk; the
polished combined-navigable-diff UI is post-MVP.

- [ ] `ViewRecorded` event is already in the vocabulary — use it
- [ ] Pin event offset on first review open per batch
- [ ] Point-in-time reconstruction via `rebuild_projections(up_to_offset=...)`
- [ ] **Snapshot cache from day one** — key on `(project_id, event_offset)`, store reduced projection; snapshots are immutable (never invalidated, only garbage-collected), so the cache is a pure optimization on the log-walk path
- [ ] Per-component review UI: walks pending nodes in topological order
- [ ] Fragment diff rendering (before/after side-by-side per fragment)
- [ ] Fan-in nodes skipped in review scoping
- [ ] UI distinguishes **destructive** (blocking, requires approval) from **non-destructive** (informational, already propagated) changes so users learn which ones actually need attention
- [ ] Accept on a destructive change releases the halted cascade; accept on a non-destructive change is informational only

## Phase 12 — Change summaries

- [ ] Every generation prompt appends a change-summary section
- [ ] Parser strips the summary from stored content, writes to a structured change log
- [ ] Queryable audit history endpoint
- [ ] Feeds into review UI (the summary is what gets shown as the diff header)

## Phase 13 — Plan nodes + code generation leaf pass

The bottom of the DAG. Code is not generated directly from impl
nodes — each impl change produces a single-use **plan node** which
is the user's gate point before any code is written. Code gen
consumes the plan, not the impl.

**Plan nodes:**
- [ ] `plan` tier node, single-use, generated when an impl node changes
- [ ] One "live" plan per impl at a time via a current-pointer; old plans kept in the event log for audit
- [ ] Plan prompt: current impl + prior impl + dep `pubapi` fragments + project language settings → structured list of (file, region, change) tuples + prose explanation
- [ ] Plan is a parseable output: generate-parse validation loop (retry-then-escalate)
- [ ] **Plans are independently gated** from the impls that produced them — approving an impl is permission to plan; approving the plan is permission to write code
- [ ] Plans read earlier plans + their generated code from within the same batch, so cross-impl coherence falls out of dep topo order
- [ ] Plans are destructive by default (they imply code mutations), so they halt the cascade at the user until approved

**Code generation:**
- [ ] Per-project language setting (Catapult = Elixir), inherited from the sysarch `techspec`
- [ ] Code regen prompt: plan node + dep `pubapi` fragments + language conventions (no impl node)
- [ ] Language-specific validator (compile / typecheck hook) as parse-validate loop
- [ ] Retry-then-escalate on persistent failures
- [ ] Dependency topological execution order, one plan at a time
- [ ] Generated code written to the project's git repo (v1 git plumbing survives)
- [ ] Plan is considered consumed once code is generated; event log retains it for audit

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
- [ ] Polished combined-navigable-diff review UI with version-dropdown navigation (MVP ships a simpler per-component walk; auto-propagation of non-destructive changes is already MVP)
- [ ] View-history snapshot optimization beyond the basic Phase 11 cache
- [ ] Multi-user concurrency on the pending-change queue
- [ ] WebSocket push instead of polling

---

## How to use this file

- Open a new phase by writing a plan under `/root/.claude/plans/` (same shape as `cheeky-soaring-token.md`) before coding.
- Flip `[ ]` → `[~]` when the plan is approved and work starts.
- Flip `[~]` → `[x]` only when the phase is merged and the acceptance test in the phase's own plan is green.
- Don't add new phases without updating the architecture doc's MVP scope section first. Scope creep dies here.
