# SiegeEngine

AI-powered project scaffolding pipeline. Takes a project description and generates system architectures, component designs, implementation plans, and working code through an 8-stage pipeline with AI + human review gates.

## Tech Stack

- **Backend**: Python, FastAPI, SQLAlchemy (SQLite w/ WAL), Claude CLI for all LLM generation
- **Frontend**: React 18, TypeScript, Vite, Zustand, Tailwind CSS, React Flow (DAG), Monaco Editor
- **Deployment**: Fly.io, Docker

## Project Layout

```
siege-engine/
  backend/
    main.py              # FastAPI app entry, lifespan, routes, SPA serving
    config.py            # Settings (SIEGE_ env prefix)
    models.py            # SQLAlchemy ORM (Project, Artifact, Pipeline*, StageExecution)
    database.py          # SQLite + WAL setup
    auth/                # JWT auth, registration, invite links
    chat/                # WebSocket chat with Claude CLI
    cli/manager.py       # Claude CLI subprocess manager (semaphore concurrency)
    dag/service.py       # DAG traversal, staleness propagation
    git_manager/         # GitPython wrapper (commit, diff, push)
    github/              # OAuth + PR creation
    pipeline/
      engine.py          # Orchestrator: sequential stages, fan-out, review gates
      events.py          # Event type constants (RUN_CREATED, STAGE_STARTED, etc.)
      reducer.py         # Pure reducer: apply_event(snapshot, event) → new snapshot
      event_store.py     # Append events, update materialized PipelineSnapshot
      routes.py          # Pipeline API endpoints
      nodes/
        generate.py      # CLI-based artifact generation
        ai_review.py     # AI review feedback generation
        extract_components.py  # 3-way consensus component extraction
      prompts/
        base.py          # PromptTemplate ABC
        requirements.py  # System + component requirements
        architecture.py  # System architecture (outputs component JSON)
        component_arch.py
        high_level_plan.py
        component_plan.py
        codegen.py       # Code generation (full tool access)
        code_review.py   # Code review + auto-fix
        ai_review_prompt.py
    projects/            # Project CRUD
    websocket/           # Real-time pipeline progress broadcasting
  frontend/
    src/
      api/               # Axios client with auth
      components/
        dag/             # PipelineDAG, StageNode (React Flow + Dagre)
        editor/          # ArtifactEditor (Monaco, markdown, diff view)
        pipeline/        # ReviewPanel, StageStatus, PromptEditorPanel
        chat/            # ChatPanel (WebSocket)
      hooks/             # useWebSocket (pipeline progress)
      pages/             # Login, ProjectList, ProjectCreate, ProjectDashboard
      store/             # Zustand: authStore, projectStore, pipelineStore, dagStore
      types/             # TypeScript interfaces
```

## Pipeline Stages

1. **System Requirements** — project-level document generation
2. **System Architecture** — project-level document
3. **Component Extraction** — extracts components via 3-way consensus voting
4. **Component Architectures** — fan-out per component
5. **Sub-Component Extraction** — fan-out per component, extracts sub-components
6. **Component Plans** — fan-out, leaf components only (no sub-components)
7. **Sub-Component Architectures** — fan-out per sub-component
8. **Sub-Component Plans** — fan-out per sub-component
9. **Code Generation** — fan-out per leaf entity, full tool access, git repo, $5 budget
10. **Code Review & Fix** — fan-out per leaf entity, full tool access

Stages 1-8 produce markdown documents via Claude CLI with web research tools.
Stages 9-10 run in the project's git repo with full tool access (bash, file editing).

## Key Patterns

- **Event sourcing**: All pipeline state changes go through events (`pipeline/events.py` → `reducer.py` → `event_store.py`). The `PipelineSnapshot` is the **single source of truth** for pipeline state. DB model status fields (`Artifact.status`, `StageExecution.status`) are projections — written for query convenience but never read for state decisions. The snapshot carries artifact metadata (name, type, component_key via `artifact_meta`), execution mapping (`execution_map`), and all statuses.
- **CLI-based generation**: All LLM calls go through Claude CLI subprocess (`cli/manager.py`), not direct API. Enables tool access, budget control, and reproducibility.
- **Semaphore concurrency**: `MAX_CONCURRENT_LLM_CALLS` (default 5) limits parallel CLI invocations.
- **Review gates**: Pipeline pauses at `awaiting_review` status (read from snapshot). Frontend shows ReviewPanel for approve/reject/edit. Resume via `POST /api/pipeline/{project_id}/resume`.
- **Staleness propagation**: Editing/rejecting an artifact emits `STALENESS_PROPAGATED` events marking downstream artifacts as stale via BFS traversal.
- **Prompt customization**: Each stage's system message, output format, and context template are editable via the PromptEditorPanel and stored in DB (PromptConfig).
- **WebSocket broadcasting**: Pipeline progress events stream to frontend in real-time.
- **Setup component**: `project_setup` is injected for code stages to ensure scaffolding runs before component code.

## Debugging Pipeline State

The user may paste debug info from the **Debug State panel** (the info-circle button in the dashboard header). The **Repair button** (gear icon) is immediately to its left. Both are in `frontend/src/pages/ProjectDashboardPage.tsx`.

### Reading the Debug Dump

The debug dump has these sections, in order:

1. **PROJECTION DRIFT DETECTED** (only if mismatches exist) — Shows where the snapshot and DB disagree. The snapshot is always correct; DB fields are stale projections.
   ```
   ARTIFACT System Architecture (4656763f): snapshot=rejected  db=generating
   STAGE system_architecture: snapshot=rejected  db=running
   ```

2. **SNAPSHOT** — The authoritative pipeline state built from events:
   - `is_running` / `is_paused` / `current_run_id` / `last_seq` — pipeline-level status
   - `run_status` — status of each run (running/completed/failed/cancelled)
   - `stage_statuses` — current status of each stage (approved/rejected/running/failed/etc.)
   - `artifact_statuses` — current status of each artifact
   - `stage_errors` — error messages per stage
   - `stage_triggers` — what triggered each stage (clean_slate_migration, rejection_regenerate, pipeline_run)
   - `execution_map` — which execution+artifact is "current" for each stage (key for reconcile)
   - `artifact_meta` — artifact type and component key

3. **RUNS** — All pipeline runs with status, timestamps, loop count, stop point

4. **EXECUTIONS** — All stage executions with status, artifact link, run link, retry count. Look for:
   - `running` executions with no matching active jobs = **stuck/orphaned**
   - Same execution_id across multiple runs = **execution reuse bug**
   - Multiple `running` executions for same stage = **duplicate regeneration**

5. **ARTIFACTS** — All artifacts with status, version, content size, file path

6. **RECENT EVENTS** — The event log (last N events). Each event has sequence number, type, run_id, timestamp, and payload. Key patterns to look for:
   - `stage_started` with `execution_id: null` = **flush-before-emit bug** (execution ID not generated before event)
   - `run_completed` appearing BEFORE `human_rejected` for same run = run completed while artifact was still awaiting review
   - Multiple `stage_started` or `stage_failed` for same execution = **duplicate processing**
   - No `stage_started` after `run_created` = execution created in DB but event never emitted

7. **ACTIVE JOBS** — Currently running background jobs. If this shows `(none)` but executions are `running`, the execution is stuck.

### Repair & Reconcile

- **Repair button** (gear icon, dashboard header): Calls `POST /pipeline/{project_id}/reconcile`. Rebuilds the snapshot from events, then syncs DB projections to match. Also fixes stuck runs and orphaned executions. Shows "Fixed N issues" result.
- **Reconcile endpoint** (`routes_pipeline.py`): Rebuilds snapshot via `EventStore.rebuild_snapshot()`, syncs artifact statuses, execution statuses (from `execution_map`), marks orphaned RUNNING executions as FAILED, and completes stuck RUNNING runs.
- **Reconstruct endpoint** (`POST /pipeline/{project_id}/reconstruct`): Disaster recovery — wipes all pipeline state and rebuilds from git + siege-state.json. Nuclear option.

### Key Debugging Files

| File | What to look at |
|------|-----------------|
| `backend/pipeline/stage_execution.py` | `StageExecutionContext`, `StageExecutionStrategy` ABC, `ForceRestartStrategy`, `ManualTriggerStrategy` — strategy pattern for stage execution setup |
| `backend/pipeline/artifact_ops.py` | `_regenerate_stage`, `resume_stage`, `retry_stage`, `_try_complete_run` — where executions are created and state transitions happen |
| `backend/pipeline/engine.py` | `_run_stage` (takes `StageExecutionContext`), `execute_strategy`, `_find_and_execute_next` — the stage execution lifecycle |
| `backend/pipeline/reducer.py` | Pure event reducer — maps event types to snapshot mutations. No DB access. |
| `backend/pipeline/event_store.py` | `emit()` — appends event, flushes, updates materialized snapshot. `rebuild_snapshot()` — replays all events from scratch. |
| `backend/pipeline/queue.py` | Job queue worker. `recover_stale_jobs()` re-queues running jobs on restart. `_handle_resume_stage` / `_handle_retry_stage` — job handlers. |
| `backend/pipeline/routes_pipeline.py` | `reconcile_statuses` — the repair endpoint. `debug_state` — generates the debug dump. |
| `frontend/src/pages/ProjectDashboardPage.tsx` | Debug button, repair button, repair handler |
| `frontend/src/components/pipeline/DebugStatePanel.tsx` | Formats the debug dump text |

### Known Pitfalls & Patterns

1. **Atomic commit ordering**: When creating an execution and emitting its STAGE_STARTED event, the correct order is:
   ```python
   self.db.add(new_execution)
   self.db.flush()          # Generate the DB ID
   self.events.emit(...)    # Emit event (uses the ID, flushes event row)
   self.db.commit()         # Commit execution + event atomically
   ```
   If you commit before emitting, a crash between commit and emit leaves a DB execution with no corresponding event (snapshot doesn't know about it). If you emit before flushing, execution_id is null in the event payload.

2. **CancelledError vs Exception**: `asyncio.CancelledError` inherits from `BaseException`, not `Exception`. Async handlers that do cleanup in `except Exception` will miss cancellations (e.g., from force-restart). Always add a separate `except asyncio.CancelledError` handler that cleans up then re-raises. See `engine.py`'s `_run_stage` for the reference pattern.

3. **Concurrency guards**: Before creating a new RUNNING execution, always check for existing RUNNING/AI_REVIEW executions for the same stage_key/component_key. `_trigger_single_stage` and `_trigger_fan_out_stage` in `engine.py` have this guard. `_regenerate_stage` and `retry_stage` in `artifact_ops.py` also have it now.

4. **Job dedup**: `enqueue()` has no built-in deduplication. Call `cancel_jobs_by_type()` before `enqueue()` to prevent duplicate jobs (see `routes_stage.py` `force_restart_stage` and `trigger_stage` for examples).

5. **recover_stale_jobs on restart**: When the server restarts, `recover_stale_jobs()` re-queues any jobs that were running. If the previous handler already created an execution before the crash, the re-queued handler will try to create another one — the concurrency guard (pitfall #3) prevents this from causing duplicates.

6. **Stage execution strategy pattern**: All stage execution goes through `_run_stage(ctx: StageExecutionContext)`, which handles the shared lifecycle (STAGE_STARTED event, generation, AI review, error handling, artifact recovery, run completion via `_try_complete_run` in its `finally` block). Trigger-specific setup lives in strategy classes in `stage_execution.py`:
   - `ForceRestartStrategy` — force-restart a failed/stuck execution
   - `ManualTriggerStrategy` — manual stage trigger (single or fan-out entity)
   - `RejectionRegenerateStrategy` — regenerate after human rejection
   - `ArtifactRevisionStrategy` — revise an approved artifact with feedback

   To add a new trigger: subclass `StageExecutionStrategy`, implement `prepare()`, call `engine.execute_strategy(strategy)`. The orchestrator (`_find_and_execute_next`) builds `StageExecutionContext` directly since it has complex multi-stage logic. Context fields `error_artifact_status` and `original_artifact_id` control error recovery per trigger type.

## Development Principles

- **Always use the long-term solution.** If there's a better architectural approach, implement it now rather than using a quick fix with plans to refactor later. Writing code is fast — don't put off refactors due to time constraints.

## Development

```bash
# Backend
source .venv/bin/activate
uvicorn backend.main:app --reload --port 8000

# Frontend
cd siege-engine/frontend && npm run dev   # localhost:5173, proxies to :8000
```

## Environment Variables

All use `SIEGE_` prefix. Key ones: `SIEGE_ANTHROPIC_API_KEY`, `SIEGE_JWT_SECRET_KEY`. See `backend/config.py` for full list.
