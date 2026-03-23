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

The user may paste debug info from the **Debug State panel** (the info-circle button in the dashboard header). The **Repair button** (gear icon) is immediately to its left. The **Error Log** (warning-triangle button with red badge) is to the right of the debug button. All three are in `frontend/src/pages/ProjectDashboardPage.tsx`.

### Error Log Panel

The **Error Log** button (warning triangle icon, next to the debug button) opens a panel showing all frontend errors captured since the last page refresh. A red badge shows the error count. This is designed for mobile debugging where browser devtools aren't available.

**What gets captured:**
- Unhandled promise rejections (global `unhandledrejection` listener)
- Global JS errors (`window.onerror`)
- WebSocket fetch failures (DAG refresh, artifact fetch)
- Visibility refresh failures (tab-refocus fetches)
- Dashboard init fetch failures (fetchProject, fetchConfig, fetchStatus, fetchRuns, fetchBlockingPR)
- React error boundary catches (both top-level `ErrorBoundary` and panel-level `PanelErrorBoundary`)

Each error entry shows: timestamp, source label (e.g. `WS fetch`, `VisibilityRefresh`, `Dashboard.fetchRuns`, `PanelErrorBoundary(Review panel error)`), error message, and expandable stack trace.

The **Copy All** button copies every error as formatted text for easy pasting into bug reports. The **Clear** button resets the log.

**Key files:**
- `frontend/src/store/errorLogStore.ts` — Zustand store, `pushError(source, error)` API
- `frontend/src/components/pipeline/ErrorLogPanel.tsx` — UI with copy/clear
- `frontend/src/main.tsx` — Global `unhandledrejection` and `error` listeners

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
| `backend/pipeline/engine.py` | `_run_stage` (takes `StageExecutionContext`), `execute_strategy`, `_find_and_execute_next` (re-looping stage scanner with cross-run guards and pre-execution pause checks) — the stage execution lifecycle |
| `backend/pipeline/reducer.py` | Pure event reducer — maps event types to snapshot mutations. No DB access. |
| `backend/pipeline/event_store.py` | `emit()` — appends event, flushes, updates materialized snapshot. `rebuild_snapshot()` — replays all events from scratch. |
| `backend/pipeline/queue.py` | Job queue worker. `_handle_resume_stage` / `_handle_retry_stage` — job handlers. `cancel_all_stale_jobs()` cleans up on startup. |
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

3. **Concurrency guards — cross-run**: Before creating a new RUNNING execution, always check for existing RUNNING/AI_REVIEW executions for the same stage_key/component_key **across ALL runs**, not just the current run. The strategy classes (`ForceRestartStrategy`, `RejectionRegenerateStrategy`, etc.) in `stage_execution.py` query project-wide. The orchestrator `_find_and_execute_next` in `engine.py` has both a stage-level cross-run inflight check and per-entity guards before creating executions. Previous bug: the inflight check was scoped to `run_id`, so concurrent runs could create duplicate executions for the same stage.

4. **Job dedup**: `enqueue()` checks for existing queued jobs with the same type + payload before creating duplicates. Call `cancel_jobs_by_type()` before `enqueue()` for additional safety (see `routes_stage.py` `force_restart_stage` and `trigger_stage` for examples).

5. **No stale job recovery**: `recover_stale_jobs()` was removed. On server restart, the startup reconciliation marks orphaned RUNNING executions as FAILED and completes stuck runs. Users restart work manually via the UI, which creates fresh runs and executions rather than resuming stale state.

6. **Stage execution strategy pattern**: All stage execution goes through `_run_stage(ctx: StageExecutionContext)`, which handles the shared lifecycle (STAGE_STARTED event, generation, AI review, error handling, artifact recovery, run completion via `_try_complete_run` in its `finally` block). Trigger-specific setup lives in strategy classes in `stage_execution.py`:
   - `ForceRestartStrategy` — force-restart a failed/stuck execution
   - `ManualTriggerStrategy` — manual stage trigger (single or fan-out entity)
   - `RejectionRegenerateStrategy` — regenerate after human rejection
   - `ArtifactRevisionStrategy` — revise an approved artifact with feedback

   To add a new trigger: subclass `StageExecutionStrategy`, implement `prepare()`, call `engine.execute_strategy(strategy)`. The orchestrator (`_find_and_execute_next`) builds `StageExecutionContext` directly since it has complex multi-stage logic. Context fields `error_artifact_status` and `original_artifact_id` control error recovery per trigger type.

7. **Run completion must be centralized**: `_try_complete_run()` is called in `_run_stage`'s `finally` block — this is the ONE place where runs are completed. Earlier bugs had run completion scattered across callers (`retry_stage`, `trigger_stage`, etc.) or missing entirely, causing zombie runs that stayed RUNNING forever. Never add run completion logic outside of `_run_stage`'s finally.

8. **Snapshot status vs DB status in API responses**: The `/status` endpoint uses snapshot `stage_statuses` as the source of truth for execution badges. But it must only apply the snapshot status to the **current** execution (the one in `execution_map`). Historical executions must use their own DB status. Otherwise every execution for a stage shows the same badge (e.g., all 21 executions for `system_architecture` blinking "Running").

9. **Startup reconciliation**: On server startup, `auto_reconcile_all_projects()` runs for every project. It rebuilds snapshots from events, syncs DB projections, marks orphaned RUNNING executions as FAILED, completes stuck runs, and cancels stale queued jobs. This replaces the old `recover_stale_jobs()` approach which tried to resume work and caused duplicate executions.

10. **Pipeline reset must clear everything**: `reset_all` must clear: all executions, all artifacts, all events, all pipeline snapshots, all component definitions, all prompt configs, AND all queued jobs. Missing any of these causes ghost state (e.g., zombie `run_status` entries from the snapshot surviving a reset, or stale jobs re-triggering after reset).

11. **DB projections are write-only for pipeline state**: `Artifact.status`, `StageExecution.status`, and similar DB fields are updated for query convenience and UI display, but pipeline state decisions must ALWAYS read from the `PipelineSnapshot`. When drift is detected between snapshot and DB, the snapshot wins. The reconcile endpoint fixes drift by syncing DB → snapshot.

12. **CLI concurrency**: `MAX_CONCURRENT_LLM_CALLS` is set to 1. Higher values caused resource issues. The semaphore in `cli/manager.py` enforces this. Don't increase without load testing.

13. **Phase boundary enforcement**: `_should_pause` must be checked BEFORE entering a stage's execution loop, not after. The check acts as a gate: stages past the stop point (e.g. `extract_sub_components` when the run stops at `component_architectures`) are never entered. Previously the check was after execution, so boundary-crossing stages ran before the pause was detected.

14. **Cascading readiness re-loop**: `_find_and_execute_next` wraps its stage scan in a `while True` loop. After each pass that did work, it re-scans all stages. This handles cascading dependencies — e.g., generating component A's architecture unlocks component B (which depends on A). Without the re-loop, B would be missed because the scan already moved past `component_architectures`.

15. **`_carry_over_approved` mismatch reconciliation**: When carrying over approved executions into a new run, the mismatch reconciliation only syncs AWAITING_REVIEW and REJECTED executions whose artifacts are APPROVED. Old FAILED retries are excluded — promoting them emits spurious `HUMAN_APPROVED` events that flood the event log. If you see a burst of `human_approved` events all at the same timestamp, this reconciliation is the likely source.

16. **Snapshot dict isolation**: `_snapshot_to_dict` in `event_store.py` uses `copy.deepcopy` on all JSON column values, not shallow `dict()` copies. Shallow copies share nested objects with SQLAlchemy-managed references, which can cause "Set changed size during iteration" when the reducer's `copy.deepcopy` iterates over nested values.

17. **Resume runs must NOT be component-scoped**: `RunFromNodeControls` in ReviewPanel.tsx passes `start_component_key` to scope runs. For Resume runs, this must be `null` — otherwise only the viewed component is processed and siblings are silently skipped by `_is_in_run_scope`. Fresh Start runs may scope to a single component. StageConfigPanel's resume already omits `start_component_key`.

## Development Principles

- **Always use the long-term solution.** If there's a better architectural approach, implement it now rather than using a quick fix with plans to refactor later. Writing code is fast — don't put off refactors due to time constraints.

### Safe-by-default async error handling

All Zustand stores use `createSafeStore` (`frontend/src/store/createSafeStore.ts`) instead of bare `create()`. This wrapper automatically catches errors from every async store action and logs them to errorLogStore. It also marks promise rejections as "handled", so fire-and-forget calls like `fetchStatus(projectId)` never cause unhandled rejection crashes.

**Do NOT add manual `.catch()` handlers to store action calls** unless the component needs to update UI on error (e.g. show a "Failed" message, reset a loading spinner). The middleware handles it.

**To add a new store:** Use `createSafeStore('storeName', (set, get) => ({ ... }))`.

**Error logging layers (from innermost to outermost):**

| Layer | Source | What it catches |
|-------|--------|----------------|
| API interceptor | `api/client.ts` | Every HTTP error (status + URL context) |
| Store middleware | `store/createSafeStore.ts` | Every store action failure (store.action name) |
| Safe hooks | `hooks/useSafe.ts` | Errors in useEffect/useMemo/useCallback bodies |
| Error boundaries | `components/ErrorBoundary.tsx` | React render crashes (panel label) |
| Global handler | `main.tsx` | Stray rejections from non-store code |

All layers log to `errorLogStore` → visible in the Error Log panel.

The `errorLogStore` itself uses bare `create()` (not `createSafeStore`) to avoid circular dependencies.

### Safe hook wrappers (`hooks/useSafe.ts`)

React error boundaries only catch errors during render. Errors in useEffect, useMemo, and callbacks are NOT caught and will crash the page. Safe hook wrappers catch those errors, log them to errorLogStore, and return safe fallbacks.

**Always use safe hooks in dashboard-level and data-heavy components:**

| Hook | Use instead of | Behavior on error |
|------|---------------|-------------------|
| `useSafeEffect(label, effect, deps)` | `useEffect` | Catches sync throws, logs to errorLogStore |
| `useSafeMemo(label, factory, fallback, deps)` | `useMemo` | Returns fallback value on error |
| `useSafeCallback(label, callback, deps)` | `useCallback` | Catches errors, logs them, re-throws for async |

The `label` parameter appears in error log entries (e.g. `useSafeEffect(dashboard-init)`).

### Zustand store subscriptions — ALWAYS use selectors

**NEVER use bare `useXxxStore()` without a selector.** Bare calls subscribe to the ENTIRE store — every state change triggers a re-render, even unrelated ones. This causes render storms, especially with WebSocket events that update `lastWSEvent` on every message.

```tsx
// BAD — re-renders on every WS event, every fetch, every state change
const { isRunning, currentRunNumber } = usePipelineStore();

// GOOD — only re-renders when these specific values change
const isRunning = usePipelineStore((s) => s.isRunning);
const currentRunNumber = usePipelineStore((s) => s.currentRunNumber);
```

This applies to ALL stores: `usePipelineStore`, `useProjectStore`, `useDAGStore`, `useAuthStore`, `useErrorLogStore`.

### Test mocks must support selector calls

When components use individual selectors (`useStore((s) => s.field)`), test mocks must handle the selector function. Use this pattern:

```tsx
let mockState: Record<string, unknown> = {};

vi.mock('../../store/pipelineStore', () => ({
  usePipelineStore: vi.fn((selector?: (s: Record<string, unknown>) => unknown) => {
    return selector ? selector(mockState) : mockState;
  }),
}));

function mockStoreValues(values: Record<string, unknown>) {
  mockState = { ...defaults, ...values };
  vi.mocked(usePipelineStore).mockImplementation(((selector?: (s: any) => any) =>
    selector ? selector(mockState) : mockState) as any);
}
```

## Quality Gates

**All frontend changes must pass these checks before committing:**

```bash
cd siege-engine/frontend
npm run typecheck    # tsc -b --noEmit (catches type errors; -b follows project references)
npm run test:run     # vitest run (unit tests)
npm run lint         # eslint (code quality)
npm run build        # vite production build
```

Or run all at once: `npm run ci`

The Docker build (`Dockerfile` stage 1) runs `typecheck`, `test:run`, and `build` in sequence — a type error or test failure will fail the deploy.

**Backend changes** should be tested with `pytest` from the repo root.

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
