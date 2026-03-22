# Run System Overhaul — Implementation Plan

## Summary of Changes

The run system shifts from an "approval-driven" model to a "scoped generation session" model. Runs start from a specific node, generate descendants up to a configured stop point, and never auto-approve. Approval becomes a passive, non-triggering action. Dependencies are satisfied by "generated" status (not just approved).

---

## Step 1: Update Enums & Models

**Files:** `backend/models/enums.py`, `backend/models/pipeline.py`

### 1a. Replace `StopPoint` enum values
```python
# Old:
AFTER_ALL = "after_all"
BEFORE_CODE = "before_code"
AT_FAN_OUT = "at_fan_out"
AFTER_TRIPLETS = "after_triplets"

# New:
END_OF_PHASE = "end_of_phase"       # Stop at end of current pipeline DAG phase
BEFORE_CODE = "before_code"          # Stop before code_generation stage
EVERY_ARTIFACT = "every_artifact"    # Stop after every single wave (most granular)
```

### 1b. Add `start_node` fields to `PipelineRun` model
- Add `start_stage_key: str | None` — the stage_key the run starts from (e.g., `component_architectures`)
- Add `start_component_key: str | None` — optional component key for fan-out scoping
- Remove `human_review: bool` column (all artifacts now go to human review; no auto-approve)

### 1c. DB migration
- Alembic migration to add `start_stage_key`, `start_component_key` columns
- Remove `human_review` column (or keep as deprecated, always True)

---

## Step 2: Update Schemas (Backend API Contracts)

**File:** `backend/pipeline/schemas.py`

### 2a. `PipelineStartRequest`
```python
class PipelineStartRequest(BaseModel):
    ai_loops: int = 1
    stop_point: str = "end_of_phase"  # "end_of_phase", "before_code", "every_artifact"
    start_stage_key: str | None = None       # Which stage to start from
    start_component_key: str | None = None   # Optional component scoping
```
- Remove `human_review` field

### 2b. `ResumeRunRequest`
- Same changes: remove `human_review`, add `start_stage_key`, `start_component_key`

---

## Step 3: Overhaul Dependency / Readiness Checks

**File:** `backend/pipeline/readiness.py`

### 3a. Change dependency check from "approved" to "generated"
The key conceptual change: `_has_approved_artifact()` and `_has_approved_execution()` should check for "generated" (i.e., has been through generation) rather than strictly "approved". Rename to `_has_generated_artifact()` / `_has_generated_execution()`.

A node's dependencies are satisfied when all parents have been **generated** — meaning their status is in: `awaiting_review`, `approved`, or `stale`. These all indicate the artifact has content.

### 3b. Update snapshot status checks
Currently checks `status == "approved"`. Change to check `status in ("approved", "awaiting_review", "stale")`.

### 3c. Update `_stage_fully_complete()`
For run-continuation purposes, a stage is "fully generated" when all entities have been generated (not necessarily approved). Rename or add a parallel method `_stage_fully_generated()` to distinguish from the existing completion check (which may still be needed for other purposes).

### 3d. Add scope filtering
- New method: `_is_in_run_scope(stage_def, component_key, run: PipelineRun)`
- Returns True if the stage/component is a descendant of the run's starting node
- For runs starting from a component node: only stages at or after that component's stage, and only that component + its sub-components
- For runs starting from a system-level node: all stages at or after that stage's order

---

## Step 4: Overhaul `_should_pause()` Logic

**File:** `backend/pipeline/engine.py`

### 4a. New stop-point logic
```python
def _should_pause(self, stage_def, pipeline_run):
    stop = pipeline_run.stop_point
    start_order = <order of pipeline_run.start_stage_key>

    if stop == StopPoint.EVERY_ARTIFACT:
        return True  # Always stop after generating one wave

    if stop == StopPoint.BEFORE_CODE:
        return stage_def.stage_key in ("code_generation", "code_review")

    if stop == StopPoint.END_OF_PHASE:
        # "Phase" = one pipeline DAG stage_key (e.g., all component_architectures)
        # If run started from a completed phase, target is the next phase
        target_order = start_order
        if <starting phase already complete>:
            target_order = start_order + 1
        return stage_def.order_index > target_order
```

### 4b. Remove all `human_review` checks from pause logic
Since all generated artifacts now go to `AWAITING_REVIEW`, the pause logic only controls whether the run *continues generating more nodes* or halts.

### 4c. Remove `BRANCHING_STAGES` special-case pausing
Branching stages no longer have special pause rules — they follow the same stop-point rules as everything else.

---

## Step 5: Overhaul `_run_stage()` — Always AWAITING_REVIEW

**File:** `backend/pipeline/engine.py`

### 5a. Remove auto-approve path
Currently `_run_stage()` has:
```python
if should_await_review:
    → AWAITING_REVIEW
else:
    → APPROVED (auto-approve)
```

Change to: **always** set status to `AWAITING_REVIEW` after generation + AI review. Delete the auto-approve branch entirely.

---

## Step 6: Overhaul `_find_and_execute_next()` — Scoped Execution

**File:** `backend/pipeline/engine.py`

### 6a. Add scope filtering to the main loop
When iterating stages, skip any stage/entity that isn't in scope for this run's `start_stage_key` / `start_component_key` using the `_is_in_run_scope()` method from Step 3d.

### 6b. Handle "every_artifact" mode
In `EVERY_ARTIFACT` mode: generate the starting node + all immediate children whose dependencies are met, then stop. "Immediate children" = next-stage entities that depend on the starting node.

### 6c. Handle "end_of_phase" with completed starting phase
If the run starts from a node whose phase is already fully generated, the effective target phase becomes the next phase (order_index + 1). Determine this at run start and store or compute dynamically.

### 6d. Change pending work semantics
Nodes in `AWAITING_REVIEW` no longer block the run from continuing. Only `RUNNING`/`AI_REVIEW` states represent truly in-flight work. The run can generate downstream nodes of `AWAITING_REVIEW` parents.

### 6e. Completion condition
A run completes when:
- No more in-scope stages have ready work to generate, AND
- No in-flight (RUNNING/AI_REVIEW) work exists

---

## Step 7: Decouple Approval from Run Continuation

**File:** `backend/pipeline/artifact_ops.py`

### 7a. `resume_stage()` with action="approved"
- Still marks artifact as APPROVED
- **Does NOT call `_check_and_continue()`** — approval alone never triggers generation
- Emits approval event for UI update only

### 7b. `resume_stage()` with action="rejected"
- Marks artifact for regeneration
- Creates a new run (or attaches to an active run) for the regeneration
- The regeneration respects run stop-point rules

### 7c. Simplify `accept_and_cascade()`
- Approve the artifact
- Start a new scoped run from that node (replaces the inline cascade loop)

---

## Step 8: Ensure All Regenerations Belong to a Run

**File:** `backend/pipeline/artifact_ops.py`

### 8a. `_regenerate_stage()`
When a user rejects and triggers regeneration:
1. Find the active run for this project, or create a new single-artifact run
2. Attach the regeneration execution to that run
3. Apply the run's stop_point rules

### 8b. Manual `trigger_stage()`
- Also creates a run (or attaches to active run)
- Default stop point: `EVERY_ARTIFACT` for manual triggers

---

## Step 9: Update Routes

**File:** `backend/pipeline/routes_pipeline.py`

### 9a. `POST /{project_id}/start`
- Accept new request fields: `start_stage_key`, `start_component_key`
- Remove `human_review` from request
- Store start node on PipelineRun

### 9b. `POST /{project_id}/resume-run`
- Same changes as start

### 9c. `POST /{project_id}/resume` (approval/rejection endpoint)
- Approval action: update status only, no run continuation
- Rejection action: create regeneration run

---

## Step 10: Update Frontend — PipelineControls

**File:** `frontend/src/components/pipeline/PipelineControls.tsx`

### 10a. Remove human review checkbox
- Delete the `humanReview` state and checkbox UI

### 10b. Update stop point dropdown
```typescript
const STOP_POINTS = [
  { value: 'end_of_phase', label: 'Stop at end of current phase' },
  { value: 'before_code', label: 'Stop before code generation' },
  { value: 'every_artifact', label: 'Stop after every artifact' },
];
```

### 10c. Add "start from node" capability
- When a node is selected in the DAG, the "Start Run" action uses that as the starting node
- Pass `start_stage_key` and `start_component_key` to the API
- If no node is selected, default to the first incomplete stage

---

## Step 11: Update Frontend — ReviewPanel

**File:** `frontend/src/components/pipeline/ReviewPanel.tsx`

### 11a. Approval should not trigger continuation
- "Approve" button marks as approved, no run continuation
- Remove any implicit "approval continues pipeline" behavior

### 11b. Rework "Accept & Cascade"
- Rename to "Approve & Regenerate Downstream" or similar
- Behavior: approve this artifact, then start a new run scoped from this node

---

## Step 12: Update Frontend Types & API

**Files:** `frontend/src/types/pipeline.ts`, `frontend/src/api/pipeline.ts`, `frontend/src/store/pipelineStore.ts`

### 12a. Update `PipelineRun` type
- Remove `human_review`
- Add `start_stage_key: string | null`, `start_component_key: string | null`

### 12b. Update API calls
- Remove `human_review` from start/resume payloads
- Add `start_stage_key`, `start_component_key`

### 12c. Update store actions
- `startPipeline()` and `resumeRun()` accept new params

---

## Step 13: Update Frontend — StageConfigPanel

**File:** `frontend/src/components/pipeline/StageConfigPanel.tsx`

### 13a. Remove per-stage `human_review_enabled` checkbox
Since all artifacts always go to human review, the per-stage toggle is no longer meaningful. Keep `ai_review_enabled` (AI review loops still happen).

---

## Execution Order

1. **Steps 1-2** (models, schemas, migration) — foundation
2. **Step 3** (readiness) — change dependency semantics from "approved" to "generated"
3. **Steps 4-6** (engine) — core execution logic overhaul
4. **Steps 7-8** (artifact_ops) — approval/regeneration decoupling
5. **Step 9** (routes) — API surface changes
6. **Steps 10-13** (frontend) — UI changes

---

## Key Behavioral Summary

| Aspect | Old | New |
|--------|-----|-----|
| Dependencies satisfied by | Approved parents | Generated parents (awaiting_review/approved/stale) |
| After generation | May auto-approve | Always AWAITING_REVIEW |
| Approval action | Triggers downstream generation | Status update only, no continuation |
| Run start | From beginning of pipeline | From a specific node |
| Run scope | Entire pipeline | Descendants of starting node |
| Stop points | after_all, before_code, at_fan_out, after_triplets | end_of_phase, before_code, every_artifact |
| Human review toggle | Checkbox per-run + per-stage | Removed — always on |
| Regeneration | Could be orphaned | Always belongs to a run |
| Phase definition | N/A | One pipeline DAG stage_key (e.g. all component_architectures) |
| End of phase (from completed phase) | N/A | Advances to next phase |
