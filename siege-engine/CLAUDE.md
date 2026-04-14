# SiegeEngine — Claude Code session notes

Working notes for Claude Code sessions on this repo. Read this first
after resuming, then `git log --oneline -20` to catch up on recent
commits. Canonical architecture docs live under
`docs/architecture/`; this file captures operational stuff + anything
load-bearing that hasn't made it into a plan file yet.

## Layout

Repo root: `/home/user/SiegeEngine`. The Python/JS project lives
under `/home/user/SiegeEngine/siege-engine/` — run all commands from
there unless noted. Backend is FastAPI + SQLAlchemy under `backend/`;
frontend is Vite + React + TypeScript under `frontend/`.

Event-sourced model: every write goes through
`backend.graph.reducer.append_event`; projections (nodes, edges,
fragments, drafts) are derived from the event log. Read `docs/architecture/v2-rearchitecture.md`
for the data model and `docs/architecture/v2-roadmap.md` for the
phase plan. The current branch is `claude/review-architecture-docs-YoIiI`.

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
npx tsc -b --noEmit
npm run lint
npx vite build
```

Always nuke `.mypy_cache` before declaring mypy clean. Past sessions
hit this twice (`Component.kind` in Phase 3, `SubcomponentSummary.parent_id`
in Phase 4) where a stale cache masked a real type error.

## Git conventions

- Develop on `claude/review-architecture-docs-YoIiI`. Never push to
  main without explicit permission.
- Commit messages: short first line, 2-4 line body explaining the why,
  trailing `https://claude.ai/code/session_01VhwPhMYZwXQ2Lx7L61CKMe` link.
- Never `--no-verify` / `--amend` / force-push without being asked.
- Prefer adding files by name over `git add -A` when there's a risk
  of sweeping in unrelated state.

## Phase status (as of last session)

**Complete:** Phases 0-5 landed. The v2 bootstrap chain runs
end-to-end: project → expansion → features → requirements → sysarch
→ subreqs (per top-level comp) → comparch (per top-level comp) →
policy application → subcomparch (per subcomponent). Frontend has
per-tier draft panels, dashboard tabs, decomposition graph, and the
Phase 5 subcomponent comparch page.

**Next (Phase 6):** Presentational nodes + domain-parent edges.
Unified DAG where domain and presentational share shape and
distinguish by `kind` (already in the schema as `domain` /
`presentational`). Presentational nodes are strictly layered after
domain and pull context from domain pubapi + domain-parent siblings.
Roadmap items:

- Presentational variants of feature / responsibility / component prompts
- `domain_parent` edge type already in schema — add editor support
- Structured UI #6: domain-parent editor (Cytoscape reuse)
- Regen prompt context for presentational nodes

Phase 7 is fan-in synthesis, Phase 8 is impl nodes. Don't conflate
them — in an earlier session I mis-remembered Phase 6 as impl nodes,
which was wrong.

## Known design debt (not urgent, worth tracking)

- **Topological dispatch within a parent comp's subcomparch batch.**
  Currently the comparch_mint fan-out enqueues `v2.generate_subcomparch`
  for every minted subcomponent at once, and the worker processes
  them in FIFO order. Subs that generate early see skeletal pubapis
  for their siblings; later-generating subs see richer context.
  Works fine for MVP but is a quality optimization for later. See
  the Phase 5 plan file for the original discussion.

- **Mint handler idempotency for node-creating tiers.** The reducer
  idempotency fix (`92a0f8f`) made `FragmentUpdated` and `EdgeCreated`
  safely re-applicable, which covers `subcomparch_mint` completely.
  But `comparch_mint`, `sysarch_mint`, `feature_mint`, etc. still
  create new nodes with fresh IDs on each run, so they need their
  own "already minted" guard checks. Those guards exist today and
  work; just noting that the reducer-level fix doesn't solve the
  node case by itself.

- **Frontend/backend contract drift.** Zod schemas on the frontend
  and Pydantic models on the backend are written by hand. Two type
  errors have slipped through before — would benefit from a generated
  or checked contract layer. Low priority.

- **Worker loop concurrency.** Handler tests call handlers directly;
  the real worker-loop polling / locking / retry path is only exercised
  by `tests/v2/test_full_bootstrap_chain.py` in a single-threaded drain
  variant. No concurrency test exists for the real loop.

- **Phase 4 alias scheme stays.** Phase 5 subcomparch uses real
  `comp_*` IDs throughout (`a85f5f2`), but Phase 4 comparch and Phase 3
  sysarch still use the alias scheme in `<subcomponents>` /
  `<sub-dependencies>` and `<components>` / `<dependencies>`. This is
  deliberate — those tiers declare brand-new entities that don't have
  IDs yet at generation time, and pre-minting IDs would shift complexity
  rather than remove it. See the design discussion in the session log.

## Seed document

The project dogfoods itself — the input document for the primary dev
project is SiegeEngine's own architecture. There's an open thread to
replace this with a real-world catapult spec so dogfooding exercises
more representative input shapes; that's a content task the user
wants to workshop interactively rather than delegating. Not a code
change.

## Things to not relitigate

- Decomposition graph layering (L0/L1/L2/L3+ with reachability) is
  Phase 11 territory. Don't try to add it earlier.
- Structured UI #4 (subresp → subcomp mapping editor) is deferred to
  Phase 11 structural-edit territory. The read-only view is already
  visible via the decomposition graph.
- Playwright / full browser E2E testing is deferred until the UI
  stops churning (probably Phase 8 or 9). The full bootstrap chain
  integration test gets most of the value at 5% of the maintenance
  cost.
