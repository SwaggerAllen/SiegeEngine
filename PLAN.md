# SiegeEngine Architecture Redesign — Implementation Plan

## Overview

This plan covers architectural improvements to SiegeEngine while keeping SQLite and the Claude CLI subprocess approach. The changes fall into 6 workstreams that can be developed mostly independently.

---

## Workstream 1: Incremental Revisions + Diff View

**Problem:** Every revision regenerates artifacts from scratch. This is slow, expensive, and forces the reviewer to re-read the entire document to find what changed.

### 1.1 Backend: Incremental Revision Prompting

**Files:** `backend/pipeline/prompts/base.py`, all prompt subclasses, `backend/pipeline/nodes/generate.py`, `backend/pipeline/artifact_ops.py`

**Approach:** When revising an existing artifact (not generating for the first time), pass the current content as context and instruct the LLM to produce only the updated version with targeted changes.

- Add a `revision_mode` parameter to `PromptTemplate.build()` that distinguishes first-generation from revision.
- When `revision_mode=True`:
  - Include the **current artifact content** in the prompt as a "CURRENT DOCUMENT" section.
  - Include a **summary of what changed upstream** (diff of upstream artifact changes that triggered staleness).
  - Replace the generic "produce a complete document" instruction with "revise the existing document to incorporate the following changes, keeping unchanged sections intact."
- In `generate.py`, before calling the CLI, detect whether this is a revision (artifact already has content + version > 0 or has feedback) and set `revision_mode` accordingly.
- In `artifact_ops.py`, `revise_artifact()` and `_regenerate_stage()` should both pass `revision_mode=True`.

**Key detail:** Store the **previous content** before overwriting so we can compute diffs. Add `previous_content` column to `Artifact` (or store in git history, which we already have — prefer git history to avoid bloating the DB).

### 1.2 Upstream Change Summaries

**Files:** `backend/pipeline/engine.py`, `backend/pipeline/artifact_ops.py`, `backend/dag/service.py`

When a downstream artifact is STALE because an upstream changed:
- Compute a text diff (unified diff format) between the upstream artifact's previous and current versions using git history (`git diff <old_sha> <new_sha> -- <file_path>`).
- Pass this diff as an `upstream_changes` field in the prompt context.
- The revision prompt says: "The following upstream documents have changed. Here are the diffs: {upstream_changes}. Update your document accordingly."

**Implementation:**
- Add `get_artifact_diff(artifact_id) -> str` to `dag/service.py` that uses `git_manager` to produce a unified diff between the last two versions.
- Add `get_upstream_change_summary(artifact_id) -> str` to `dag/service.py` that walks upstream dependencies and collects diffs for any that changed since this artifact was last generated.
- Thread this through `_gather_inputs()` as an additional `upstream_changes` key.

### 1.3 Frontend: Diff View

**Files:** `frontend/src/components/editor/ArtifactEditor.tsx`, new component `frontend/src/components/editor/DiffView.tsx`, `frontend/src/api/pipeline.ts`

- Add a new API endpoint `GET /api/pipeline/{project_id}/artifacts/{artifact_id}/diff` that returns a unified diff between the current version and the previous version (from git).
- Add a `DiffView` component using a lightweight diff renderer (e.g., `react-diff-viewer-continued` or a simple unified-diff renderer with Tailwind styling).
- In `ArtifactEditor`, add a "Diff" tab (between "Document" and "AI Feedback") that shows the diff when version > 1 or when the artifact was just revised.
- For STALE artifacts awaiting re-review, default to showing the diff tab so reviewers can quickly see what changed.

### 1.4 API Endpoint

**Files:** `backend/pipeline/routes_stage.py` or new `backend/pipeline/routes_artifact.py`

```
GET /api/pipeline/{project_id}/artifacts/{artifact_id}/diff
  Query params: ?base_version=N (optional, defaults to version-1)
  Response: { diff: string, from_version: int, to_version: int, from_sha: string, to_sha: string }
```

Uses `git_manager` to compute `git diff <from_sha> <to_sha> -- <file_path>`.

---

## Workstream 2: Remove Component-Level Requirements

**Problem:** Component requirements are busywork — they add a full pipeline stage that doesn't contribute enough value relative to the system requirements + component architecture.

### 2.1 Remove `component_requirements` Stage

**Files:** `backend/pipeline/defaults.py`, `backend/pipeline/readiness.py`, `backend/pipeline/engine.py`, `backend/pipeline/prompts/`

**Changes:**
- Remove `component_requirements` from `DEFAULT_STAGES` (order_index 3).
- Re-index remaining stages (component_architectures becomes order 3, etc.).
- Update `COMPONENT_STAGE_ORDER` in `readiness.py` to remove `"component_requirements"`.
- Update `component_architectures` stage's `input_stage_keys` to pull from `[extract_components, system_requirements, system_architecture]` instead of `[component_requirements, system_architecture]`.
- Update `extract_sub_components` stage's `input_stage_keys` similarly.
- Update `component_plans` stage's `input_stage_keys` to use `system_requirements` instead of `component_requirements`.
- Remove `ComponentRequirementsPrompt` class and its registry entry.
- Update `ComponentArchPrompt` to include system requirements as context (it currently only gets component requirements + system architecture).

### 2.2 Remove `sub_component_requirements` Stage

**Files:** Same as above.

**Changes:**
- Remove `sub_component_requirements` from `DEFAULT_STAGES`.
- Re-index remaining stages.
- Update `SUB_COMPONENT_STAGE_ORDER` in `readiness.py`.
- Update `sub_component_architectures` input to pull from `[extract_sub_components, component_architectures, system_requirements]`.
- Update `sub_component_plans` input similarly.
- Remove `SubComponentRequirementsPrompt` class.
- Update `SubComponentArchPrompt` to include system requirements context.

### 2.3 Update Artifact Types

**Files:** `backend/models.py`

- Keep the `COMPONENT_REQUIREMENTS` and `SUB_COMPONENT_REQUIREMENTS` enum values for backward compatibility with existing projects, but they won't be created for new projects.
- Add a migration note: existing projects with these artifacts keep them; new projects skip them.

### 2.4 Update Frontend

**Files:** `frontend/src/types/pipeline.ts`, DAG visualization components

- The DAG visualization is driven by `StageDefinition` records in the DB, so it will automatically reflect the removed stages for new projects.
- No hard-coded stage references to remove (already checked — the frontend is data-driven).

### 2.5 Resulting Pipeline (10 stages, down from 12)

```
0. system_requirements        (none)
1. system_architecture        (none)      ← inputs: [system_requirements]
2. extract_components         (none)      ← inputs: [system_requirements, system_architecture]
3. component_architectures    (component) ← inputs: [extract_components, system_requirements, system_architecture]
4. extract_sub_components     (component) ← inputs: [component_architectures, system_requirements]
5. component_plans            (component) ← inputs: [component_architectures, system_requirements, extract_components]
6. sub_component_architectures (sub_comp) ← inputs: [extract_sub_components, component_architectures, system_requirements]
7. sub_component_plans        (sub_comp)  ← inputs: [sub_component_architectures, component_architectures]
8. code_generation            (leaf)      ← inputs: [component_plans, component_architectures, sub_component_plans, sub_component_architectures]
9. code_review                (leaf)      ← inputs: [code_generation, component_plans, component_architectures, sub_component_plans, sub_component_architectures]
```

---

## Workstream 3: Additional Input Documents + Change Propagation

**Problem:** Users can't add supplementary documents (API specs, design docs, brand guidelines, etc.) as inputs that feed into the pipeline. When new requirements/features are added, there's no way to propagate changes through the DAG and review all the resulting updates.

### 3.1 Input Documents Model

**Files:** `backend/models.py`, new migration

Add a concept of **input documents** beyond the single project description:

- Add `InputDocument` model:
  ```python
  class InputDocument(Base):
      id: str (UUID)
      project_id: str (FK)
      name: str              # "API Specification", "Brand Guidelines", etc.
      content: str           # The document content
      doc_type: str          # "reference" | "requirements" | "constraints"
      version: int           # Incremented on updates
      created_at: datetime
      updated_at: datetime
  ```
- Add relationship on `Project`: `input_documents = relationship("InputDocument")`

### 3.2 Input Document CRUD API

**Files:** New `backend/pipeline/routes_input_docs.py`, `backend/pipeline/routes.py` (to include router)

```
GET    /api/pipeline/{project_id}/input-docs          → list all
POST   /api/pipeline/{project_id}/input-docs          → create new
PUT    /api/pipeline/{project_id}/input-docs/{doc_id} → update content
DELETE /api/pipeline/{project_id}/input-docs/{doc_id} → delete
```

On **update**: increment version, mark all downstream artifacts as STALE (everything depends on inputs), broadcast `staleness_propagated` via WebSocket.

On **create**: mark system_requirements as STALE (the root of the pipeline) so changes propagate on next run.

### 3.3 Wire Input Documents into Prompts

**Files:** `backend/pipeline/engine.py` (`_gather_inputs`), prompt classes

- In `_gather_inputs()`, for the `system_requirements` stage (which currently only gets `project_doc`), also fetch all `InputDocument` records and include them as additional context:
  ```
  inputs["project_doc"] = project.description
  inputs["input_documents"] = "\n\n---\n\n".join(
      f"### {doc.name} ({doc.doc_type})\n\n{doc.content}"
      for doc in project.input_documents
  )
  ```
- Update `SystemRequirementsPrompt` context template to include `{input_documents}` section.
- For architecture and downstream stages, input documents are transitively available through the system requirements artifact. But for reference docs (API specs, etc.), also inject them directly into relevant stages. Add an `inject_into_stages` field on `InputDocument` that lists which stages should receive this document directly (default: `["system_requirements"]`).

### 3.4 Change Propagation + "In Review" Behavior

**Files:** `backend/pipeline/artifact_ops.py`, `backend/pipeline/engine.py`

**Current behavior:** When `human_review=False`, artifacts auto-approve after generation/AI review.

**New behavior:** When `human_review=False` AND the run was triggered by input document changes (or manual "propagate changes" action):
- After an artifact finishes regeneration, set its status to `AWAITING_REVIEW` instead of auto-approving.
- This lets the user review all changes that came from introducing new requirements.
- The pipeline continues generating downstream nodes (they see the upstream as AWAITING_REVIEW, which is already treated as "available" by `_gather_inputs`).
- The user can then go through and review/approve each node at their leisure.

**Implementation:**
- Add a `propagation_run` boolean on `PipelineRun` (default False). Set to True when the run is started via input document update or a "propagate changes" action.
- In `_run_stage()`, after generation completes: if `propagation_run=True`, always go to `AWAITING_REVIEW` regardless of `human_review` setting.
- In the find-next-ready logic, treat `AWAITING_REVIEW` artifacts as valid inputs (already the case).

### 3.5 "Propagate Changes" Action

**Files:** `backend/pipeline/routes_pipeline.py`, `backend/pipeline/engine.py`

New endpoint:
```
POST /api/pipeline/{project_id}/propagate
  Body: { artifact_ids?: string[] }  // optional: specific artifacts to regenerate from
  Response: { run_id, stale_count, regeneration_order }
```

This:
1. Marks downstream artifacts as STALE (if not already).
2. Creates a new `PipelineRun` with `propagation_run=True`.
3. Regenerates stale artifacts in dependency order using incremental revision (Workstream 1).
4. Each regenerated artifact lands in `AWAITING_REVIEW`.

### 3.6 Frontend: Input Documents Panel + Propagation UI

**Files:** New `frontend/src/components/input-docs/InputDocPanel.tsx`, `frontend/src/pages/ProjectDashboardPage.tsx`, `frontend/src/api/pipeline.ts`, `frontend/src/store/`

- Add "Input Docs" tab to the project dashboard (alongside Documents, Pipeline, Prompts, Chat, Settings).
- Panel shows list of input documents with add/edit/delete.
- Editor for each doc (Monaco or textarea).
- "Propagate Changes" button that calls the propagate endpoint.
- After propagation, DAG view highlights AWAITING_REVIEW nodes so the user can click through and review diffs.

---

## Workstream 4: Proper Alembic Migrations

**Problem:** The current migration system is ad-hoc (manual ALTER TABLE in `database.py`). This makes schema changes fragile and hard to track.

### 4.1 Initialize Alembic

**Files:** New `alembic/` directory, `alembic.ini`, `backend/database.py`

- Run `alembic init alembic` in the `siege-engine/` directory.
- Configure `alembic/env.py` to use `backend.models.Base.metadata` and read `SIEGE_DATABASE_URL` from config.
- Create initial migration that matches the current schema (stamp as "initial" without running, since tables already exist in production).

### 4.2 Migration for New Features

Create Alembic migrations for:
- `InputDocument` table (Workstream 3).
- `PipelineRun.propagation_run` column.
- Any removed columns or renamed fields.

### 4.3 Startup Integration

**Files:** `backend/database.py`, `backend/main.py`

- Replace the current ad-hoc migration logic in `database.py` with `alembic.command.upgrade("head")` on startup.
- Keep the WAL mode pragma and recovery logic.
- Remove the manual `_maybe_migrate_*` functions.

### 4.4 SQLite Considerations

- Use `render_as_batch=True` in Alembic's `env.py` for SQLite compatibility (ALTER TABLE limitations).
- Test that migrations work both on fresh DBs and existing production DBs.

---

## Workstream 5: Job Queue (Replace asyncio Background Tasks)

**Problem:** Pipeline stages run as `asyncio.create_task()` fire-and-forget coroutines. If the server restarts, running work is lost. There's no retry, no visibility into queued work, no backpressure.

### 5.1 Adopt ARQ (Async Redis Queue) or SQLite-based Queue

Since we're staying on SQLite and want minimal infrastructure, use a **SQLite-backed job queue** rather than Redis.

**Option A: SAQ (Simple Async Queue)** — supports SQLite backend, async-native, lightweight.
**Option B: Custom SQLite queue** — a `job_queue` table with status, payload, retry logic.

**Recommendation: Option B (custom)** — keeps dependencies minimal and SQLite-native. The pipeline already has execution tracking in `StageExecution`; we extend it to be the queue.

### 5.2 Worker Model

**Files:** New `backend/worker.py`, `backend/pipeline/queue.py`

- Add a `job_queue` table:
  ```python
  class Job(Base):
      id: str (UUID)
      job_type: str          # "run_stage", "propagate", "revise"
      payload: JSON          # {project_id, stage_key, component_key, run_id, ...}
      status: str            # "queued", "running", "completed", "failed", "cancelled"
      priority: int          # Lower = higher priority
      max_retries: int
      retry_count: int
      locked_at: datetime    # For distributed locking
      locked_by: str         # Worker ID
      created_at: datetime
      completed_at: datetime
      error_message: str
  ```
- Worker loop (runs in-process as an asyncio task, but reads from DB):
  ```python
  async def worker_loop():
      while True:
          job = claim_next_job()  # SELECT ... WHERE status='queued' ORDER BY priority LIMIT 1; UPDATE SET status='running'
          if job:
              await execute_job(job)
          else:
              await asyncio.sleep(1)
  ```
- Concurrency: Use the existing semaphore from `CLIManager` to limit concurrent CLI calls.

### 5.3 Integrate with Pipeline Engine

**Files:** `backend/pipeline/engine.py`, `backend/pipeline/artifact_ops.py`, `backend/pipeline/routes_pipeline.py`

- Replace `asyncio.create_task(self._run_stage(...))` with `enqueue_job("run_stage", {...})`.
- Replace `_run_in_background()` in routes with `enqueue_job()`.
- On server startup, mark any `status='running'` jobs as `status='failed'` (recovery, same pattern as current `StageExecution` recovery).
- Worker picks up jobs and calls the same `_run_stage()` logic.

### 5.4 Benefits

- **Crash recovery:** Jobs persist in DB; restarted worker picks up queued work.
- **Visibility:** Query `job_queue` table to see pending/running/failed jobs.
- **Backpressure:** Worker only claims N jobs at a time based on semaphore.
- **Cancellation:** Set job status to `cancelled`; worker checks before starting.

---

## Workstream 6: Decompose models.py

**Problem:** All 15+ ORM models in a single file makes navigation difficult and creates a risk of circular imports as the codebase grows.

### 6.1 Split into Domain Modules

**New structure:**
```
backend/models/
    __init__.py          # Re-exports everything for backward compatibility
    base.py              # Base class, common mixins
    auth.py              # User, InviteLink
    project.py           # Project, InputDocument
    artifact.py          # Artifact, ArtifactDependency, ArtifactComment
    pipeline.py          # PipelineConfig, PipelineRun, StageDefinition, StageExecution, PromptConfig
    component.py         # ComponentDefinition
    enums.py             # All enums (ArtifactStatus, ArtifactType, FanOutStrategy, etc.)
    job.py               # Job (from Workstream 5)
```

### 6.2 Migration Strategy

- `__init__.py` re-exports all models: `from backend.models.artifact import *` etc.
- This means all existing imports (`from backend.models import Artifact`) continue to work.
- Gradually update imports across the codebase to use specific modules.
- Alembic sees the same `Base.metadata` regardless of file organization.

---

## Implementation Order

These workstreams have some dependencies:

```
Workstream 6 (models decomposition)  ──┐
Workstream 4 (Alembic)               ──┼── Foundation (do first)
                                        │
Workstream 2 (remove component reqs) ──┤── Can be done independently
                                        │
Workstream 5 (job queue)             ──┤── Needs models + Alembic
                                        │
Workstream 1 (incremental revisions) ──┤── Independent, but benefits from 2
                                        │
Workstream 3 (input docs + propagation)┘── Depends on 1 (incremental) + 4 (Alembic)
```

**Recommended order:**
1. **Workstream 6** — Models decomposition (low risk, pure refactor)
2. **Workstream 4** — Alembic setup (enables all future schema changes)
3. **Workstream 2** — Remove component requirements (simplifies pipeline)
4. **Workstream 5** — Job queue (improves reliability)
5. **Workstream 1** — Incremental revisions + diff view (major feature)
6. **Workstream 3** — Input documents + change propagation (builds on 1 + 4)

---

## Scope Notes

**Explicitly out of scope:**
- SQLite → Postgres migration (keeping SQLite for deployment simplicity)
- CLI subprocess → API SDK (keeping CLI for max subscription benefits + skills + train of thought)
- Frontend framework changes (keeping React + Zustand + Tailwind)
- Auth system changes (JWT + invite system is working fine)
