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

**Complete:** Phases 0 through 7.5.

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

**Next:** Phase 8 remaining work + Phase 11 structural edit UIs
(domain-parent editor, subresp → subcomp mapping editor). The
pending-change queue has storage + instruction types but the HTTP
plumbing isn't exposed yet — that lands with Phase 11.

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

- Decomposition graph layering (L0/L1/L2/L3+ with reachability)
  is Phase 11 territory. Don't try to add it earlier.
- Structured UI #4 (subresp → subcomp mapping editor) is
  deferred to Phase 11 structural-edit territory. The read-only
  view is already visible via the decomposition graph.
- Playwright / full browser E2E testing is deferred until the UI
  stops churning. The full bootstrap chain integration test gets
  most of the value at 5% of the maintenance cost.

## Deployment

- **Fly.io**: deploys from `siege-engine/fly.toml`, region `iad`.
- **CD**: `.github/workflows/deploy.yml` — deploys on push to
  `main` via `flyctl deploy --remote-only`.
- **CI**: `.github/workflows/ci.yml` runs on PRs only (frontend
  typecheck/test/build, backend lint/typecheck/test). CI and
  deploy are decoupled — merging to main triggers deploy
  regardless of CI.
