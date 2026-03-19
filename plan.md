# Plan: Scale Machine Resources — Status Sync, Consistency, Entity Preconditions

Three structural improvements to prevent execution/artifact status mismatches and entity-missing bugs.

---

## Phase 1: Status Transition Helper

**Goal:** Centralize execution + artifact status updates into a single method so they can't get out of sync.

### 1a. Create `_transition_status()` method on `PipelineEngine`

**File:** `backend/pipeline/engine.py` (replace existing `_mark_awaiting_review` and `_mark_approved`)

```python
def _transition_execution(
    self,
    execution: StageExecution,
    new_status: StageStatus,
    *,
    artifact_status: ArtifactStatus | None = None,
    error_message: str | None = None,
    set_completed: bool = False,
) -> None:
    """Atomically transition execution status and optionally its artifact.

    Args:
        execution: The execution to update.
        new_status: Target StageStatus.
        artifact_status: If provided, also update the linked artifact to this status.
        error_message: If provided, set on execution.error_message.
        set_completed: If True, set execution.completed_at = now.
    """
```

- Sets `execution.status = new_status`
- If `set_completed`, sets `execution.completed_at = datetime.utcnow()`
- If `error_message`, sets `execution.error_message = error_message`
- If `artifact_status` and `execution.artifact_id`, fetches and updates the artifact
- Logs the transition: `"Transition exec %s: %s -> %s (artifact: %s)"`

This does NOT broadcast — callers still handle their own websocket events (per your preference).

### 1b. Replace existing helpers

- Delete `_mark_awaiting_review` and `_mark_approved` from engine.py
- Replace their call sites with `_transition_execution`

### 1c. Migrate direct status assignments

Replace all direct `execution.status = X` / `artifact.status = Y` patterns across:

| File | Approx. call sites to migrate |
|------|------|
| `engine.py` | 6 execution + 4 artifact → ~5 calls to `_transition_execution` |
| `artifact_ops.py` | 11 execution + 12 artifact → ~10 calls |
| `routes_stage.py` | 2 execution + 2 artifact → 2 calls |

**Not migrated** (intentionally):
- `generate.py` artifact GENERATING status — internal to artifact creation
- `routes_pipeline.py` batch cancel — special bulk update
- Artifact-only STALE propagation in `_cascade_reject_downstream` / `_invalidate_stale_downstream` — these don't have an execution context, add a separate `_mark_artifact_stale()` helper instead

### 1d. Add `_mark_artifact_status()` for artifact-only transitions

For cases where only the artifact status changes (STALE propagation, resolve_stale):

```python
def _mark_artifact_status(self, artifact_id: str, new_status: ArtifactStatus) -> None:
```

---

## Phase 2: Consistency Check

**Goal:** Detect and fix execution/artifact status mismatches. Called at pipeline start and available via API.

### 2a. Create `_reconcile_statuses()` method

**File:** `backend/pipeline/engine.py`

```python
def _reconcile_statuses(self, project_id: str, run_id: str) -> list[dict]:
    """Find and fix execution/artifact status mismatches for a run.

    Returns list of corrections made (for logging/API response).
    """
```

**Mismatch rules to check:**

| Execution Status | Artifact Status | Action |
|---|---|---|
| APPROVED | not APPROVED (except STALE) | Set artifact → APPROVED |
| AWAITING_REVIEW | not AWAITING_REVIEW | Set artifact → AWAITING_REVIEW |
| FAILED | GENERATING or AI_REVIEWING | Set artifact → PENDING (unstick) |
| REJECTED | not REJECTED/STALE | Set artifact → REJECTED |
| any terminal | GENERATING | Set artifact → PENDING (unstick) |

Each correction gets logged and returned in the corrections list.

### 2b. Wire into pipeline start

**File:** `backend/pipeline/engine.py`

Call `_reconcile_statuses` in `start_pipeline()` and `resume_run()` after `_carry_over_approved` but before `_find_and_execute_next`.

### 2c. Expose as API endpoint

**File:** `backend/pipeline/routes_pipeline.py`

```python
@pipeline_router.post("/{project_id}/reconcile")
async def reconcile_statuses(project_id: str, ...):
    """Manually trigger status reconciliation for the latest run."""
```

Returns the list of corrections made (or empty list if clean).

---

## Phase 3: Fan-out Entity Precondition Check

**Goal:** Make entity existence self-healing — if ComponentDefinition rows are missing but the approved artifact exists, auto-populate them.

### 3a. Add self-healing to `_get_all_entities_for_stage()`

**File:** `backend/pipeline/readiness.py`

When `_get_all_entities_for_stage` returns an empty list for a fan-out stage, check if the corresponding branching artifact exists and is approved. If so, call `_post_generation_hook` to re-populate, then retry.

```python
def _get_all_entities_for_stage(self, project_id, stage_def):
    entities = <existing logic>
    if not entities and stage_def.fan_out_strategy != FanOutStrategy.NONE:
        self._heal_missing_entities(project_id, stage_def)
        entities = <retry existing logic>
    return entities
```

### 3b. Create `_heal_missing_entities()` method

**File:** `backend/pipeline/component_manager.py`

```python
def _heal_missing_entities(self, project_id: str, stage_def: StageDefinition) -> bool:
    """Attempt to re-populate missing ComponentDefinitions from approved artifacts.

    Returns True if entities were healed, False if no healing was possible.
    """
```

Logic:
- For COMPONENT fan-out: find approved `extract_components` artifact, re-run `_store_components`
- For SUB_COMPONENT fan-out: find approved `extract_sub_components` artifacts per parent, re-run `_store_sub_components`
- For LEAF fan-out: try both of the above
- Log a warning when healing occurs (indicates a prior bug)

### 3c. Add unique constraint on ComponentDefinition

**File:** New alembic migration

Add a unique constraint: `UniqueConstraint(project_id, key, parent_key)` — using a partial index or coalesce for the nullable `parent_key`.

SQLite approach (for dev): `CREATE UNIQUE INDEX uq_comp_def_key ON component_definitions (project_id, key, COALESCE(parent_key, ''))`

### 3d. Make `_store_components` / `_store_sub_components` idempotent

Already mostly idempotent (delete-then-recreate), but with the unique constraint we need to handle the upsert pattern. The existing delete-then-recreate pattern is fine with the constraint — the delete runs first.

---

## Execution Order

1. **Phase 1** first — the status helper is foundational and every other change benefits from it
2. **Phase 2** next — the consistency check uses the helper and validates the new patterns work
3. **Phase 3** last — entity preconditions are independent but benefit from the cleaner status code

## Files Modified

| File | Changes |
|------|---------|
| `backend/pipeline/engine.py` | Add `_transition_execution`, `_mark_artifact_status`, `_reconcile_statuses`; remove old helpers; migrate all status assignments |
| `backend/pipeline/artifact_ops.py` | Migrate ~10 status assignments to use new helpers |
| `backend/pipeline/routes_stage.py` | Migrate 2 status assignments |
| `backend/pipeline/routes_pipeline.py` | Add reconcile endpoint |
| `backend/pipeline/readiness.py` | Add self-healing entity check |
| `backend/pipeline/component_manager.py` | Add `_heal_missing_entities` |
| `backend/models/artifact.py` | Add UniqueConstraint to ComponentDefinition |
| `alembic/versions/new_migration.py` | Add unique index migration |

## Testing Strategy

- After Phase 1: Run existing tests — every status transition should still work identically
- After Phase 2: Write a test that creates a mismatched execution/artifact pair and verifies reconciliation fixes it
- After Phase 3: Write a test that deletes ComponentDefinitions and verifies fan-out stages still find their entities
