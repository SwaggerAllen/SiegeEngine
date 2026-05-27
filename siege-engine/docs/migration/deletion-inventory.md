# Phase 4 — Deletion inventory

This document is the punch list for the deletion sweep that removes
the legacy backend modules now that `siege/` carries the read path
and Claude Code skills carry the write path.

**Status: NARROWED.** The original inventory (written pre-step-4)
assumed the dashboard could be repointed at a deployed MCP server
before the sweep, and assumed every feature in the legacy backend
had a v3 equivalent. Neither held:

- The MCP transport was dropped (step 5) — the read API lives on
  the existing FastAPI app at `/siege/api/*`, mounted from
  `backend/main.py`.
- Several legacy features (cohorts, vocabulary, references,
  human-review batches, pending-instruction queue, feedback
  history) have **no v3 equivalent** and keep their backend in this
  round; their deletion is a follow-up.

The current sweep deletes only the **per-tier generation/review
stack**. The bigger LOC delta (models, reducer, pipeline, alembic)
ships in a later cleanup pass.

## Gates (revised)

This sweep proceeds when:

1. **Phase A** (doc reconciliation) lands — done in the same
   commit as this rewrite.
2. **Phase B** (frontend read-repoint) lands — every frontend read
   that has a `/siege/api/*` equivalent moves off `/api/*`. Once
   that lands, the per-tier read endpoints in `backend/graph/` are
   genuinely unreachable.
3. Frontend write surface is fully neutralized (Phase 3 stubbed the
   buttons; Phase B greps for any remaining onClick handlers
   firing legacy `/api/<tier>/<write>` calls).

The original MCP-server-deployed and full-chain-end-to-end gates
are dropped — neither is meaningful with the transport gone.

## What gets deleted (this round, ~5-8K LOC)

### Per-tier generation + review handlers (~3K LOC)

- `backend/graph/handlers/expansion_generation.py`
- `backend/graph/handlers/requirements_generation.py`
- `backend/graph/handlers/sysarch_generation.py`
- `backend/graph/handlers/comparch_generation.py`
- `backend/graph/handlers/subcomparch_generation.py`
- `backend/graph/handlers/impl_generation.py`
- `backend/graph/handlers/fanin_generation.py`
- `backend/graph/handlers/review_{expansion,requirements,sysarch,comparch,subcomparch,impl,fanin}.py` (7 files)
- The corresponding `_mint.py` handlers where they exist as
  separate modules
- Per-tier handler tests under `tests/v2/test_handlers_*.py` +
  `test_review_*.py`

### Write routes that drove the per-tier handlers (~1.5K LOC)

- `backend/graph/bootstrap_routes.py` — the per-tier draft /
  feedback / approve / discard / cancel / reset / retry endpoints.
- `backend/graph/tier_ops_routes.py` write functions — `reset-all`,
  `review-sweep`, `resume`, `regen-below-threshold`, `full-corpus`,
  `exploration-sample`. The read functions (`info`, `review-summary`,
  `structure-summary`, `batches`) move to `/siege/api/*` in
  Phase B; what's left after the move is deletable.

### Per-tier read projection (~1.5K LOC)

- `backend/graph/regen_context.py` — the per-tier context gatherer
  replaced by `siege/projection/_base.py` + the seven per-tier
  modules.

### LLM subprocess + websocket (~1K LOC)

- `backend/cli/manager.py` — Claude CLI subprocess wrapper. Used
  only by the per-tier handlers being deleted; skills invoke the
  LLM via Claude Code directly. **Verify** zero remaining callers
  after the handler deletion (cohort regen is the last suspect —
  if cohort regen also moves to a skill, this falls out cleanly).
- `backend/cli/` — the whole directory if `manager.py` is its
  only module.
- `backend/websocket/` — the SSE event stream. Frontend mount went
  away in Phase 3; only the deleted handlers still write to it,
  so it falls out of the dependency graph cleanly here.

### Orphaned graph projection modules

- `backend/graph/diff.py` — node-diff projection; v3 model is
  "diff via git diff body.md", no projection needed.
- `backend/graph/staleness.py` — staleness markers were a
  projection on the old node graph.
- `backend/graph/fanout.py` — fanout dispatcher tied to the
  per-tier handlers.

Verify zero inbound imports before deleting each. The surviving
cohort / vocab / ref / queue routes don't reference these.

### Tests

- `tests/v2/test_handlers_*.py`, `test_review_*.py`,
  `test_regen_*.py`, `test_bootstrap_routes.py`,
  `test_tier_ops_*.py`
- `tests/v2/test_full_bootstrap_chain.py` — the integration test
  exercises the deleted handlers; no v3 equivalent (the substrate's
  chain runs through the CLI in `siege/tests/`). Acceptable loss;
  call it out explicitly in the deletion commit.

## What stays this round (deferred to a follow-up sweep)

Features that don't have v3 equivalents — their dashboard pages
keep working against `/api/*`, so their backend modules + data
plumbing stay:

### Persistence layer (~5K LOC, deferred)

- `backend/database.py`
- `backend/alembic/` + `alembic.ini`
- `backend/models/` (12 files: `auth.py`, `batch.py`, `cohort.py`,
  `cohort_sampler_config.py`, `graph_event.py`,
  `input_document.py`, `job.py`, `node.py`,
  `pending_instruction.py`, `project.py`, `review.py`,
  `telemetry.py`)

### Job pipeline (~2K LOC, deferred)

- `backend/pipeline/` — queue, worker loop, rate limiter. The
  surviving cohort / vocab / ref / review-batch / queue paths
  still enqueue jobs.

### Surviving feature backends (~5K LOC, deferred)

- `backend/graph/cohort_routes.py`, `cohort_sampler.py`
- `backend/graph/vocabulary*`
- `backend/graph/references*`
- `backend/graph/queue_routes.py`, `jobs_routes.py`
- `backend/graph/review_routes.py` (human review batches)
- `backend/graph/feedback*` if standalone
- `backend/graph/debug_routes.py` if any
- The handlers those routes enqueue
- `backend/graph/reducer.py`, `queries.py`,
  `apply_instruction.py`, `instructions.py`,
  `pending_instruction.py` — load-bearing for the surviving
  features
- `backend/graph/tier_structure.py`, `review_summary.py` — keep
  unless Phase B fully repoints both panels at `/siege/api/*`
  (the read endpoints exist in `siege/server.py`; the wire-up is
  Phase B's job)

### Frontend modules (deferred-feature shims)

- `frontend/src/api/cohorts.ts`, `vocabulary.ts`, `references.ts`,
  `queue.ts`, `review.ts`, `feedbackHistory.ts`, `debug.ts`
- Their corresponding panels + pages
- `useQueueMutations.ts` — kept in Phase 3 as a doomed shim;
  stays until the queue page goes away

### Schemas + auth surface (stays this round)

- `backend/projects/routes.py`, `service.py`, `schemas.py`,
  `settings.py` — project CRUD + per-project settings. The
  dashboard still creates / deletes / renames projects through
  these.
- `backend/auth/routes.py`, `service.py`, `schemas.py` — login +
  JWT issuance. `siege/auth.py` is verify-only; issuance stays
  here.
- `backend/github/` — OAuth + repo provisioning.
- `backend/git_manager/` — clone + commit helpers used by both
  `siege.git_view` and the surviving feature backends.
- `backend/config.py` — shared env loading.

## What survives in `backend/` after this round

- `backend/main.py` — FastAPI app mounting `siege.server.app` at
  `/siege` plus the surviving routers.
- `backend/projects/`, `backend/auth/`, `backend/github/`,
  `backend/git_manager/`, `backend/config.py` — unchanged.
- `backend/database.py`, `backend/alembic/`, `backend/models/`,
  `backend/pipeline/` — deferred.
- `backend/graph/` — narrowed to the deferred-feature routes +
  their handlers + shared infrastructure (`reducer.py`,
  `queries.py`, `apply_instruction.py`).

## Cumulative LOC delta

This round: ~5-8K removed (per-tier generation/review + tier-ops
writes + regen_context + websocket + cli/manager + the orphaned
projection modules).

Deferred follow-up (when the deferred features either drop or grow
v3 equivalents): ~20K additional removal (models, alembic, pipeline,
reducer, cohort/vocab/ref/queue/review-batch route stacks).

## Infrastructure

- `Dockerfile` — needs editing in a follow-up: drop the alembic
  migration step + the worker process when the pipeline goes away.
  This round, no changes.
- `docker-entrypoint.sh` — same, follow-up.

## Sequencing

Two commits, in this order:

1. `phase 4c1: drop per-tier generation + review handlers + bootstrap routes`
2. `phase 4c2: drop tier-ops write surface + websocket + cli/manager + orphan projections`

The siege test suite stays green throughout; legacy tests delete
with their modules.

## Rollback

The deletions live in commits on the migration branch. Rolling back
is `git revert <commit_sha>` per chunk. Persisted data (the SQLite
DB) is unaffected — the deferred persistence layer is untouched.
