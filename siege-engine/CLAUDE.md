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

**Complete:** Phases 0-5.5 landed, plus the backend slice of Phase
6. The v2 bootstrap chain runs end-to-end: project → expansion →
features → requirements → sysarch → subreqs (per top-level comp) →
comparch (per top-level comp) → policy application → subcomparch
(per subcomponent). Frontend has per-tier draft panels, dashboard
tabs, decomposition graph (with presentational kind styling and
`domain_parent` edges already rendered), the Phase 5 subcomponent
comparch page, and the Phase 5.5 vocabulary list + entry pages.

The Phase 6 backend slice in particular: `RegenContext` carries
`domain_parents` + `domain_parent_techspecs` + `domain_parent_pubapis`,
populated for presentational top-levels and inherited by subs of
presentational parents. `comparch` renders a "# This component
presents" section; `subcomparch` renders a "# Grandparent domain
context" section. The end-to-end bootstrap chain test exercises
the presentational path (BillingUI presentational comp with a
domain_parent edge to BillingDomain) and asserts both sections
land in the rendered prompts.

**Next (remaining Phase 6 work):** Structured UI #6 — the
domain-parent editor. Deferred during the Phase 6 backend slice
because the pending-change queue HTTP plumbing doesn't exist yet
(queue storage + `enqueue_instruction` + `AddDomainParent` /
`RemoveDomainParent` instruction types all exist, but no routes
expose them). Phase 11 lands the full queue UX alongside the
other structured edit UIs; #6 is effectively co-scheduled there
unless someone wants an isolated domain-parent editor first.

Phase 7 is fan-in synthesis, Phase 8 is impl nodes. Don't conflate
them — in an earlier session I mis-remembered Phase 6 as impl nodes,
which was wrong.

## Meaning-engine model (default bundle)

The engine itself is tier-agnostic (it traverses a graph of
prompt stages supplied by the active bundle). The **default
bundle's** generation chain is designed as a meaning engine —
each tier produces compressed handles (names, roles, API intents,
pubapi fragments) that downstream tiers reason from directly.
The chain alternates compression, expansion, and rotation:

- **Feature expansion** — extraction from raw input
- **Requirements** — rotation (user-facing → system-level axis)
- **Sysarch** — compression (resps → components)
- **Subreqs** — scope-bounded expansion
- **Comparch** — last compression before impl
- **Subcomparch** — leaf articulation, no more tiers to correct

Every prompt names its downstream reader, pushes against
category-speak, and frames the tier's transformation type.
Handle quality (meaning-per-token) is the load-bearing property
— if a tier's output is vague, the fix is in that tier's prompt,
not in passing more context downstream. The input doc only feeds
extraction tiers (expansion, reqs, sysarch); propagation tiers
(comparch, subcomparch, impl) work from handles only.

See `docs/architecture/v2-rearchitecture.md` §The default bundle
as a meaning engine and `seed-docs/catapult-spec-v2.md` §A.3.1a
for the full treatment.

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
