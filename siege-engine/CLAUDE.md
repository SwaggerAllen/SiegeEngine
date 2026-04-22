# SiegeEngine — Claude Code session notes

Working notes for Claude Code sessions on this repo. Read this first
after resuming, then `git log --oneline -20` to catch up on recent
commits. Canonical architecture docs live under
`docs/architecture/`; this file captures operational stuff + anything
load-bearing that hasn't made it into a plan file yet.

## Layout

Repo root: `/home/user/SiegeEngine`. The Python/JS project lives
under `/home/user/SiegeEngine/siege-engine/` — run all commands from
there unless noted. Backend is FastAPI + SQLAlchemy (SQLite, WAL)
under `backend/`; frontend is Vite + React + TypeScript + Zustand +
Tailwind under `frontend/`. All LLM calls go through the Claude CLI
subprocess (`backend/cli/manager.py`), not the Anthropic API directly.

Event-sourced model: every write goes through
`backend.graph.reducer.append_event`; projections (nodes, edges,
fragments, drafts) are derived from the event log. Read
`docs/architecture/v2-rearchitecture.md` for the data model and
`docs/architecture/v2-roadmap.md` for the phase plan. The active
branch is `claude/dragons-JF20l`.

## Verification commands

Run all of these from `siege-engine/` before claiming a change is
complete. Path gotchas matter — `ruff` / `mypy` live in `~/.local/bin/`,
not `.venv/bin/`, and mypy caches stale results aggressively.

```
# Backend
.venv/bin/python -m pytest tests/v2/ -q
ruff check backend tests && ruff format --check backend tests
rm -rf .mypy_cache && mypy backend

# Frontend (from siege-engine/frontend/)
npx vitest run
npx tsc -b --noEmit --force
npm run lint
npx vite build
```

Always nuke `.mypy_cache` before declaring mypy clean. Past sessions
hit this twice (`Component.kind` in Phase 3, `SubcomponentSummary.parent_id`
in Phase 4) where a stale cache masked a real type error. Use
`--force` on tsc to defeat its own stale-buildinfo cache.

## Development

```
# Backend
source siege-engine/.venv/bin/activate
uvicorn backend.main:app --reload --port 8000

# Frontend
cd siege-engine/frontend && npm run dev    # localhost:5173, proxies to :8000
```

Env vars use `SIEGE_` prefix (e.g. `SIEGE_ANTHROPIC_API_KEY`,
`SIEGE_JWT_SECRET_KEY`). See `backend/config.py` for the full list.

## Git conventions

- Develop on `claude/dragons-JF20l`. Never push to main without
  explicit permission.
- Commit messages: short first line, 2-4 line body explaining the
  why, trailing `https://claude.ai/code/session_...` link.
- Never `--no-verify` / `--amend` / force-push without being asked.
- Prefer adding files by name over `git add -A` when there's a risk
  of sweeping in unrelated state.

## Phase status (as of last session)

**Complete:** Phases 0 through 7.5 + Phase 8 (AI self-review) + Phase 9 (staleness ledger) + Phase 10 (layered DAG view) + Phase 11 (pending-change queue + structured edit UIs) + Phase 12 (batched review + regen-time diff).

- **Phases 0-5.5** — v2 bootstrap chain end-to-end: project →
  expansion → features → requirements → sysarch → subreqs (per
  top-level comp) → comparch (per top-level comp) → policy
  application → subcomparch (per subcomponent). Per-tier draft
  panels, decomposition graph, vocabulary, references.
- **Phase 6** — presentational components + domain-parent edges.
  `RegenContext` carries `domain_parents` + techspecs + pubapis for
  presentational tops and their subs. Comparch renders "# This
  component presents", subcomparch renders "# Grandparent domain
  context". End-to-end chain test covers the presentational path.
  Structured UI #6 (domain-parent editor) deferred to Phase 11.
- **Phase 6.6 (read-path consolidation)** — `GET /projects/:id/structure`
  snapshot + `GET /projects/:id/events/stream` SSE channel replace
  ~14 per-tier read endpoints and all client polling.
  `backend/graph/broadcast.py` runs an in-process per-project
  async pub/sub. Frontend's `useProjectEventStream` hook drives
  cache invalidations via a single event-type → queryKey dispatch
  table. Per-tier detail GETs remain but refetch on SSE events.
- **Phase 7** — fan-in synthesis (`fanin_*` nodes). Bottom-up
  summary of what a domain comp as-built actually exposes,
  driven by the `on_impl_approved` hook + `all_impls_populated_for`
  first-pass gate (see scheduling notes below).
- **Phase 7.5 backlog** — nav/UI/reset/prompts/scheduling cleanup:
  red dot errors + blue dot needs-user-action + green dot approved
  in the sidebar tree, contextual tab strip with Component Overview
  tab, force-reset buttons on every per-comp tier, techspec
  paragraph formatting, sibling-dependency pubapi + top-level
  resps in subreqs prompts, presentational comparch waits for
  domain fan-in (not comparch), fan-in waits for first-pass impl
  completion then regens on change.
- **Phase 8 (AI self-review)** — every generated draft (and fan-in
  commit) triggers a review LLM pass that critiques the
  generator's output against the same context the generator
  saw. Advisory only — never blocks approval. Lives as a
  collapsible markdown block on the draft panel, with four
  render states (idle-with-text, running, failed, hidden).
  Review failures carry their own transient-CLI retry counter
  and expose a manual "Retry review" button. See the
  "AI self-review" section below.
- **Phase 9 (staleness ledger & fanout decision)** —
  `staleness_ledger` projection table tracks which nodes are
  stale w.r.t. which upstreams. Central fanout dispatcher in
  `backend/graph/fanout.py` runs inside `append_event` after
  each trigger, walks the edges table, and mutates the ledger
  directly (derived state — not event-sourced, replay wipes
  it). Non-destructive triggers auto-enqueue regens via
  `regen_job_for_node`; destructive structural ops (delete /
  merge / split / promote / demote / reparent) halt the cascade
  so the user can review. Fuchsia stale dot in the sidebar tree
  renders orthogonally to the existing amber/red/blue/green —
  an approved-but-stale node shows green + fuchsia.
  **Scope note**: the fanout dispatcher walks edges only. The
  two bespoke hooks `on_impl_approved` (impl → owning domain
  comp's fanin) and `_unblock_presentationals_on_fanin_commit`
  (fanin → presentational comparchs gated on domain_parent)
  traverse `parent_id` structural chains, not edges, so they
  stay in place. Fanout is silent for those paths (no edges
  exist in that direction), so docs come out identical — the
  only consequence is those specific cascades don't populate
  the ledger, so the fuchsia stale badge doesn't appear on the
  fanin or presentational comparchs during the brief window
  between the impl/fanin commit and the regen running; instead
  they show pulsing-amber when the regen job picks up. Retiring
  the hooks cleanly needs either synthetic edges at mint time
  or parent-id walking in the dispatcher; deferred until a flow
  beyond scaffolding actually needs that generality.

- **Phase 10 (layered DAG view)** — single navigable canvas for
  the whole project graph. Features, top-level resps, top-level
  policies, top-level comps with `dependency` topology arranged
  by ELK's layered algorithm under cytoscape-elk. Double-click
  a comp to drill into its internal subgraph (component-local
  policies, subresps, subcomps, fan-in, revealed impls) plus an
  external-context layer that traces back to the top-level
  feats / resps / policies pointing at this comp. Single-click
  selects a node and highlights its reachable-down (yellow) and
  reachable-up (pink) subgraphs. Phase 9 staleness renders as a
  fuchsia double-border overlay — same visual language as the
  sidebar tree. Lives under `frontend/src/components/graph/`.
  Replaces the old force-directed `DecompositionGraph.tsx`.
  The DAG chunk is code-split (elkjs adds ~1.5MB), loaded lazily
  when the user clicks the "Decomposition Graph" sidebar entry.
  Sidebar synthetic id renamed from `:decomposition-graph` to
  `:dag` — label stays "Decomposition Graph" for continuity.

- **Phase 11 (pending-change queue + structured edit UIs)** —
  All six structured edit UIs shipped. Queue panel
  (list / discard / apply with halt-on-failure sequential
  invariant) lives at `QueuePanel.tsx` + `queue_routes.py`.
  Rename routes through `v2.rename_rewrite` (LLM prose rewrite).
  Graph view primary on UIs #3 / #5 / #6 via a shared
  `EditableGraph` wrapper (`components/editors/graph/`) with a
  two-tap edge-add state machine; list view preserved as the
  accessibility fallback (`Graph | List` toggle on each panel).
  `NodeActionSidebar` centralizes per-node actions (Create /
  Rename / Delete / Move / Promote / Demote / Split) on the
  Decomposition graph; Merge lives on multi-select triggered
  either by toolbar toggle or long-press (`taphold`). Sidebar
  drops to a bottom sheet below 768px via `useIsNarrowViewport`.
  A single `<QueueAnnounceRegion>` aria-live region reads out
  every successful enqueue for screen-reader users.
  Deliberately deferred (noted in "Things to not relitigate"):
  drag-to-connect and node drag-repositioning — two-tap is the
  working pattern and ELK layout is authoritative.

- **Phase 12 (batched review + regen-time diff)** —
  Four PRs landed in sequence. **12a** adds a pending-before-
  vs-pending-after diff on the Document tab for every bootstrap
  tier's Reject & Regenerate loop. "Before" resolves to the
  most-recently-discarded draft row (preserved by
  `_apply_draft_discarded` across cycles), falling back to
  approved content on first regen and to raw render on brand-
  new bootstraps. `DraftDiffView` wraps `react-diff-view` with
  a dark-theme CSS-var scope (`.diff-view-dark`) and a
  side-by-side / unified toggle. **12b** adds two primary-state
  tables: `review_batches` pins the latest `GraphEvent.offset`
  at batch open so the stale-set evaluation is stable under
  concurrent writes, and `projection_snapshots` caches JSON
  dumps of `projection_snapshot` at each offset (built via
  `rebuild_projections` inside a `session.begin_nested()`
  savepoint that rolls back after serialization so the live
  projection survives). **12c** ships the walker UI at
  `/projects/:id/review/:batchId` — tier-ranked ordered list in
  the left rail, per-node content diff + per-fragment
  accordion in the detail pane, both rendered via the same
  `DraftDiffView` the regen loop uses. Fan-in tier is excluded
  from the walker per the roadmap. **12d** wires the accept
  endpoint: non-destructive accept clears the node's ledger
  rows (downstream cascade already fired via Phase 9
  auto-enqueue); destructive accept (any
  `structural_change` reason) additionally enqueues a regen
  for the accepted node, which re-fires the halted cascade
  naturally via fanout on the new `DraftGenerated` event.
  Accept is idempotent — a second click is a no-op.
  Workspace header sprouts a `Review` button that opens a
  fresh batch; sidebar integration is deliberately minimal
  pending a multi-batch review flow.

**Next:** Phase 13 (change summaries).

## V3 spec scope vs V2 implementation

Three new seed docs describe Catapult at a higher abstraction level
than v2 implements:

- `seed-docs/catapult-spec-v3.md` — platform spec (event-sourced
  reducer, reactive schema, flows as schema deltas, two primitives,
  review/feedback, bundles, etc.)
- `seed-docs/catapult-default-bundle-v3.md` — the default bundle
  (tier/edge/fragment/structural-rules vocabulary)
- `seed-docs/catapult-default-bundle-v3-examples.md` — YAML schema
  examples, per-flow sketches, running Part 3 open-changes list

**The v2 siege engine implements the v3 default bundle's scaffolding
walk imperatively in Python.** Everything past that is v3-spec
territory, not v2 implementation.

V2 tiers/edges/structural rules already done that match v3's default
bundle:
- `feat` / `resp` / `comp` / `subcomp` / `impl` tiers
- `policy` tier + `policy_application` edges resolved at comparch
- `vocab`, `ref`, `fanin` tiers
- AI self-review
- All five fragment kinds (techspec, pubapi, privapi, policies, deps)
- All five edge instances (dependency, domain_parent,
  policy_application, decomposition, reference)
- Foundation rule, depth cap, domain/presentational DAG, fan-in
  synthesis

V2 remaining gaps in the scaffolding walk:
- `plan` tier — Phase 14
- `code` tier — Phase 14
- `manifest` bootstrap — Phase 14

V2 supporting work adjacent to scaffolding:
- Phases 9–13 (staleness, DAG view, structural edit UIs, batched
  review, change summaries)
- Phase 15 (Catapult smoke test)
- Phase 16 (project export)

Explicit v3-spec items **out of v2 scope**:
- Four non-scaffolding flows (feature-request, refactor, bug-fix,
  downward propagation, upward propagation)
- Bundle configuration system (platform spec §A.11)
- Phase-zero tier machinery
- `invokes:` primitive selector and the `downward_cascade` /
  `up_then_down` walk primitives
- `implicates_visit` edge mechanism
- `<assessment>` grammar for up-then-down flows
- Everything in the Part 3 core-platform-changes list
- Cross-project references (meta-design escape hatch)

If a future session touches anything on the out-of-scope list,
flag it and confirm the scope change is intended.

## Thinking effort per tier (B6)

The three top-of-chain tiers (feature expansion, requirements,
sysarch) pass ``thinking_effort="max"`` to
``cli_manager.generate_with_usage``. The CLI manager forwards
that as ``CLAUDE_CODE_EFFORT_LEVEL=max`` on the single
subprocess invocation (scoped per-call via
``_build_subprocess_env``, not process-wide).

Propagation tiers (comparch, subcomparch, impl, fanin,
references, reviews) deliberately leave ``thinking_effort``
unset so ``CLI_MAX_BUDGET_USD`` isn't consumed by thinking
tokens before the real reasoning finishes. Handle quality
upstream is the investment that pays off downstream; the
compression tiers don't need deep thinking because the handles
they read are already the compressed form.

## Meaning-engine model

The generation chain is a meaning engine — each tier produces
compressed handles (names, roles, API intents, pubapi fragments)
that downstream tiers reason from directly. The chain alternates
compression, expansion, and rotation:

- **Feature expansion** — extraction from raw input
- **Requirements** — rotation (user-facing → system-level axis)
- **Sysarch** — compression (resps → components)
- **Subreqs** — scope-bounded expansion
- **Comparch** — last compression before impl
- **Subcomparch** — leaf articulation, no more tiers to correct

Every prompt names its downstream reader, pushes against
category-speak, and frames the tier's transformation type.
Handle quality (meaning-per-token) is the load-bearing property —
if a tier's output is vague, the fix is in that tier's prompt,
not in passing more context downstream. The input doc only feeds
extraction tiers (expansion, reqs, sysarch); propagation tiers
(comparch, subcomparch, impl) work from handles only.

See `docs/architecture/v2-rearchitecture.md` §The system as a
meaning engine and `seed-docs/catapult-spec-v2.md` §A.3.1a for
the full treatment.

## Scheduling invariants (Phase 7.5)

- **Presentational comparch gate**: a presentational comp's
  comparch waits until every one of its `domain_parent` targets
  has a populated `fanin_*` node. Helper:
  `queries.all_domain_parents_have_populated_fanin`. Deferral
  in `subreqs_mint`; unblock walk runs in
  `fanin_generation._unblock_presentationals_on_fanin_commit`
  after each fan-in content commit.
- **Fan-in first-pass gate**: `on_impl_approved` only enqueues
  `v2.generate_fanin` when `all_impls_populated_for(owner)`
  returns true. Before first-pass, partial impl coverage leaves
  the gate closed. After first-pass, every approval re-fires
  (queue dedups on payload).
- **Reset compatibility**: clearing an impl's content via a
  per-tier force-reset flips the gate closed until re-approved.

## Tree view status model

The sidebar tree's dot badges mirror a node's real state:

- **Pulsing amber** — generation running (queued or running job)
- **Red** — latest generation job failed (`has_error`)
- **Amber** — pending draft awaiting review (`has_pending_draft`)
- **Blue** — prereqs met but idle / needs user kick
  (`needs_user_action`): latest job cancelled, or tier is ready
  to generate but hasn't been triggered (typically `impl`, or
  any tier post-cancel)
- **Green** — approved content landed (`has_content` and no
  other badge applies)
- **No dot** — upstream-blocked (prereqs not satisfied;
  waiting on the chain, not the user)

Descendant rollups emit dimmed mini-dots on collapsed ancestors
so hidden state stays visible.

The tree's pulsing-amber state spans **both** draft generation
and AI self-review generation — `running.py`'s `_TIER_JOB_TYPES`
includes the 8 `v2.review_<tier>` job types, so a draft that
committed but is still being reviewed reads as "generating" in
the sidebar. The pulse only flips off once the review job
terminates (succeeded or failed).

## AI self-review

Every approved tier has a second LLM pass that critiques the
generator's output. Reviews are advisory — approving a draft
doesn't wait on review completion — and are **automatic** after
every draft commit (gated off only by `SIEGE_DISABLE_AI_REVIEW=1`,
which the chain integration test sets so it doesn't double its
CLI call count).

- **Per-tier module triad.** Every reviewed tier has three
  matching modules: `review_context/<tier>.py` (the context
  gatherer that **both** the generator and the reviewer call so
  they see identical input), `prompts/review/<tier>.py` (the
  review prompt), and `handlers/review_<tier>.py` (the job
  handler registered as `v2.review_<tier>`). A shared
  `prompts/review/_shared.py` template + `_tier_review.py`
  wrapper keep the per-tier boilerplate to a couple dozen lines.
- **Storage.** `Draft.review_text` holds the review output for
  draft-based tiers; `Node.review_text` holds it for fan-in
  (which writes content directly to the node without a draft
  cycle). `DraftReviewUpdated` event routes by
  `target_type="draft" | "node"` and the reducer writes to the
  right row.
- **Prompt contract.** One markdown response with two top-level
  sections: `## Handles & structure` (coverage, naming, scope-
  fit, downstream-readability) and `## Architectural decisions`
  (tech-stack soundness, boundaries, anti-patterns). On tiers
  that don't make tech decisions — expansion, requirements,
  subreqs, fan-in — the second section critiques the
  decomposition axis instead.
- **Frontend render states.** `BootstrapDraftPanel` and
  `FanInPanel` both show a review block with four states keyed
  off `review_status`:
  - `idle` + non-empty `review_text` → collapsible "AI Review"
    markdown (default collapsed)
  - `running` → spinner + "Reviewing… attempt N/M"
  - `failed` → red banner showing `review_last_error` +
    "Retry review" button (wired to the per-tier
    `/review/retry` endpoint)
  - `idle` + empty `review_text` → hidden (pre-Phase-8 drafts
    and reviews-disabled mode)
- **Independent retry loop.** The review handler reuses
  `_record_attempt_progress` for transient-CLI retries, so the
  frontend gets a live attempt counter independent of the
  generator's counter. Hard failures surface as
  `review_status="failed"` + `review_last_error`.
- **Regen / reset cancels in-flight reviews.**
  `persist_draft`'s prior-draft-discard block cancels the stale
  draft's review; fan-in reset cancels its node-scoped review.
  The new draft / node starts with `review_text=""`.

## Frontend patterns

- **All Zustand stores use `createSafeStore`** (`frontend/src/store/createSafeStore.ts`)
  instead of bare `create()`. Middleware catches async action
  errors and logs to `errorLogStore`. Fire-and-forget store
  calls can't produce unhandled rejections. The `errorLogStore`
  itself uses bare `create()` to avoid circular deps.
- **Always use selectors on Zustand stores**:
  `const value = useStore((s) => s.field)`, never bare
  `const { a, b } = useStore()`. Bare calls subscribe to the
  entire store and cause render storms (especially with
  high-frequency updates like SSE events).
- **Safe hook wrappers** (`hooks/useSafe.ts`): `useSafeEffect`,
  `useSafeMemo`, `useSafeCallback` catch errors that React's
  error boundaries miss (effects, memos, callbacks) and log
  them to `errorLogStore`.
- **Test mocks** that stub a Zustand store must accept the
  selector function: `vi.fn((selector) => selector ? selector(state) : state)`.
- **Conditional polling for live attempt counters**: per-tier
  detail hooks use `runningRefetchInterval` from
  `hooks/useBootstrapHooks.ts` — polls every 2s while
  `generation_status === 'running'` so the attempt counter
  stays fresh (SSE drives event-based refetches; the Job-row
  payload carrying `_current_attempt` doesn't produce events).

## Known design debt (not urgent, worth tracking)

- **Topological dispatch within a parent comp's subcomparch batch.**
  Currently the comparch_mint fan-out enqueues
  `v2.generate_subcomparch` for every minted subcomponent at once,
  and the worker processes them in FIFO order. Subs that generate
  early see skeletal pubapis for their siblings; later-generating
  subs see richer context. Works fine for MVP but is a quality
  optimization for later.
- **Mint handler idempotency for node-creating tiers.** The
  reducer idempotency fix (`92a0f8f`) made `FragmentUpdated` and
  `EdgeCreated` safely re-applicable, which covers
  `subcomparch_mint` completely. But `comparch_mint`,
  `sysarch_mint`, `feature_mint`, etc. still create new nodes with
  fresh IDs on each run, so they need their own "already minted"
  guard checks. Those guards exist today and work; just noting the
  reducer-level fix doesn't solve the node case by itself.
- **Frontend/backend contract drift.** Zod schemas on the frontend
  and Pydantic models on the backend are written by hand. Two
  type errors have slipped through before — would benefit from a
  generated or checked contract layer. Low priority.
- **Worker loop concurrency.** Handler tests call handlers
  directly; the real worker-loop polling / locking / retry path
  is only exercised by `tests/v2/test_full_bootstrap_chain.py`
  in a single-threaded drain variant. No concurrency test
  exists for the real loop.
- **Phase 4 alias scheme stays.** Phase 5 subcomparch uses real
  `comp_*` IDs throughout (`a85f5f2`), but Phase 4 comparch and
  Phase 3 sysarch still use the alias scheme in `<subcomponents>`
  / `<sub-dependencies>` and `<components>` / `<dependencies>`.
  This is deliberate — those tiers declare brand-new entities
  that don't have IDs yet at generation time, and pre-minting IDs
  would shift complexity rather than remove it.
- **Force-reset job cancellation is project-wide.** Per-comp
  resets cancel every in-flight downstream-tier job in the
  project, not just jobs scoped to the target comp. Aggressive
  but consistent with the "force" framing; scope-aware
  cancellation is a follow-up if/when someone hits it in practice.

## Seed document

The project dogfoods itself — the input document for the primary
dev project is SiegeEngine's own architecture. There's an open
thread to replace this with a real-world catapult spec so
dogfooding exercises more representative input shapes; that's a
content task the user wants to workshop interactively rather than
delegating. Not a code change.

## Things to not relitigate

- Phase 11 closure: structured edit UIs 1–6 all shipped. Graph
  view primary on UIs #3 / #5 / #6; list view is the a11y
  fallback, not a different product. Don't add list-only
  affordances that the graph view can't reach, and don't add
  graph-only affordances that break the list fallback.
- Playwright / full browser E2E testing is deferred until the UI
  stops churning. The full bootstrap chain integration test gets
  most of the value at 5% of the maintenance cost.
- **Drag-to-connect on graph editors.** HTML5 pointer-event drag
  on Cytoscape nodes is flaky — flaky enough that two-tap is the
  working pattern on both desktop and touch. Don't try to
  reintroduce drag semantics; if someone wants a visual
  "connecting" affordance during the two-tap, draw a ghost edge
  from the selected-source instead.
- **Node drag-repositioning against ELK.** ELK is authoritative
  for layout on every graph editor. Users adjusting positions
  manually fights the layout engine and the adjustments don't
  persist through re-layouts.

## Deployment

- **Fly.io**: deploys from `siege-engine/fly.toml`, region `iad`.
- **CD**: `.github/workflows/deploy.yml` — deploys on push to
  `main` via `flyctl deploy --remote-only`.
- **CI**: `.github/workflows/ci.yml` runs on PRs only (frontend
  typecheck/test/build, backend lint/typecheck/test). CI and
  deploy are decoupled — merging to main triggers deploy
  regardless of CI.
