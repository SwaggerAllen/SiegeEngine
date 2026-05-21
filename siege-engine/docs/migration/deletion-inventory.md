# Phase 4 — Deletion inventory

This document is the punch list for the eventual deletion sweep that
removes the old SQLAlchemy + job-queue + LLM-client stack now that
`siege/` carries the read path and Claude Code skills carry the
write path.

**Don't delete yet.** Phases 1-3 are not yet validated in production.
The new MCP server hasn't been deployed; the dashboard hasn't been
repointed; the skills haven't been exercised end-to-end against a
real project repo. The deletion is gated on:

1. `siege` deployed at the target host and accepting reads from
   the dashboard.
2. The plugin installed on mobile CC and at least one full
   draft → review → approve cycle completed on a real project.
3. The dashboard fully repointed at MCP HTTP endpoints, no jobs / SSE
   traffic for ≥ 1 working session.

Once those three gates pass, the deletion below can be executed as
one or a few commits.

## What gets deleted

### Persistence layer (~5K LOC)

- `backend/database.py` — SQLAlchemy engine + session factory.
- `backend/alembic/` — all 26 migration files + alembic.ini.
- `backend/models/` (12 files):
  - `auth.py`, `batch.py`, `cohort.py`, `cohort_sampler_config.py`,
    `graph_event.py`, `input_document.py`, `job.py`, `node.py`,
    `pending_instruction.py`, `project.py`, `review.py`,
    `telemetry.py`
- `data/siege_engine.db` (and any `.db-*` siblings) — gitignored
  already, but verify before deleting the file.

### Job queue + pipeline (~2K LOC)

- `backend/pipeline/` — queue + worker loop + rate limiter.
- `backend/cli/manager.py` — Claude CLI subprocess wrapper. Skills
  invoke the LLM via Claude Code directly, not via subprocess.
- `backend/cli/` (the whole dir, if `manager.py` is the only file).
- `backend/websocket/` — SSE event stream (the frontend mount is
  already gone in Phase 3).
- `backend/graph/queue.py`, `queue_routes.py`, `jobs_routes.py`,
  `running.py`, `events.py`, `broadcast.py`, `apply_instruction.py`.

### FastAPI write routes (~6K LOC across handlers + routes)

- `backend/graph/bootstrap_routes.py` (POST endpoints that enqueued
  jobs — `bootstrap_reset`, `bootstrap_feedback`, `bootstrap_approve`,
  per-tier `/draft`, `/review/retry`).
- `backend/graph/tier_ops_routes.py` (action endpoints — `reset-all`,
  `regen-from-reviews`, `regen-below-threshold`, `full-corpus`,
  `exploration-sample`, `cohort_regenerate`).
- `backend/graph/cohort_routes.py` write surfaces.
- `backend/graph/per_comp_reset.py`.
- `backend/graph/handlers/` (entire directory — the per-tier job
  handlers don't run in the new world).
- `backend/graph/reducer.py` — event-sourced reducer. State lives in
  git now.

### Models + projections (~3K LOC)

- `backend/graph/diff.py` — node-diff projection. The new model is
  "diff via git diff body.md", no projection needed.
- `backend/graph/staleness.py` — staleness markers were a projection
  on the old node graph; not relevant when state lives in git.
- `backend/graph/fanout.py` — fanout dispatcher tied to the reducer.
- `backend/graph/references.py` — reference projection.
- `backend/graph/tier_structure.py` — replaced by `siege/structure.py`.
- `backend/graph/review.py` + `review_summary.py` — replaced by
  `siege/review_summary.py`.
- `backend/graph/regen_context.py` — replaced by per-tier readers
  in `siege/projection/`.
- `backend/graph/queries.py` — readiness gates inline in slash
  commands now; the structure summary handles enumeration.
- `backend/graph/instructions.py`, `pending_instruction.py`, etc.

### Schemas + auth surface

- `backend/projects/routes.py` — write endpoints (create / delete
  project) stay if dashboard still does CRUD on projects, otherwise
  prune.
- `backend/projects/service.py`, `schemas.py`, `settings.py` — keep
  the read paths the dashboard uses; prune writes.
- `backend/auth/routes.py`, `service.py`, `schemas.py` — `service.py`
  was ported simplified to `siege/auth.py`. If login + token
  issuance stays in the dashboard, keep the routes + password
  helpers; otherwise prune.

### Tests

Every test file whose `import` block references any of the deleted
modules:

- `tests/v2/test_pipeline_*.py`
- `tests/v2/test_queue_*.py`
- `tests/v2/test_handlers_*.py`
- `tests/v2/test_reducer_*.py`
- `tests/v2/test_bootstrap_chain.py` (the full chain integration
  test — re-targeted in `siege/tests/` at the MCP-shaped chain)
- `tests/v2/test_review_*.py`, `test_regen_*.py`, etc.

### Frontend (already done in Phase 3 except for these stragglers)

Phase 3 deleted the queue / SSE surfaces. Phase 4 cleans up:

- The `useQueueMutations.ts` shim left in place during Phase 3.
- Any `.test.tsx` files that still mock the queue API.
- The "Queue retired" landing pane introduced as a temporary
  redirect in Phase 3.

### Infrastructure

- `Dockerfile` — needs editing, not deletion: drop the alembic
  migration step + the worker process, keep the MCP server +
  frontend bundle.
- `docker-entrypoint.sh` — drop alembic upgrade + worker spawn.
- `fly.toml` — drop any process group for the worker if one exists.

## What survives in `backend/`

Post-deletion, `backend/` shrinks to:

- `backend/main.py` — slim FastAPI app that mounts `siege.server.app`
  and any remaining dashboard-only routes (projects CRUD, auth login).
- `backend/projects/` — project CRUD (read + the small set of writes
  the dashboard needs: create, delete, update name).
- `backend/auth/` — login / token issuance (the verification-only half
  lives in `siege/auth.py`).
- `backend/git_manager/` — clone + commit helpers. `siege.git_view`
  uses these for the clone-on-first-read path.
- `backend/github/` — GitHub OAuth + repo provisioning.
- `backend/config.py` — shared env loading.

That's roughly ~3K LOC remaining, down from ~30K.

## Cumulative LOC delta (estimate)

- Lines deleted: ~30K
- Lines added (siege + plugin contents): ~3.5K
- Net: ~26.5K LOC removed.

The migration trades a process-heavy backend with persistence, a job
queue, an LLM subprocess wrapper, and an SSE channel for a thin
read-only server backed by git. The meaning-engine logic doesn't
disappear — it moves into the MCP server's per-tier readers (the
~1.5K-line `regen_context.py` becomes the ~270-line `_base.py` plus
seven ~80-line per-tier modules) and the prompt text moves into the
skills themselves.

## Sequencing the actual deletion

Do it in 4 commits, one logical chunk per commit, in this order so
the test suite stays runnable between commits:

1. `phase 4a: drop job queue + worker loop + pipeline`
2. `phase 4b: drop event-sourced reducer + projections`
3. `phase 4c: drop write routes + handlers`
4. `phase 4d: drop models + database + migrations`

Tests for deleted modules disappear with each commit. The siege
test suite stays green throughout.

## Rollback

The deletions live in commits on the migration branch. Rolling back
is `git revert <commit_sha>` per chunk. Persisted data (the SQLite
DB) is the only thing that doesn't survive a revert — back it up
before the deletion sweep.
