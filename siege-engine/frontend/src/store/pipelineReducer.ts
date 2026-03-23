/**
 * Pure reducer for pipeline event sourcing.
 * Mirrors backend/pipeline/reducer.py — apply WS events to a local snapshot.
 */

import type { PipelineSnapshot, StageExecution, StageExecutionStatus, WSEvent } from '../types/pipeline';

export function emptySnapshot(): PipelineSnapshot {
  return {
    last_sequence: 0,
    run_status: {},
    stage_statuses: {},
    artifact_statuses: {},
    is_running: false,
    is_paused: false,
    paused_stage: null,
    current_run_id: null,
  };
}

/**
 * Apply a WebSocket event to a local snapshot copy.
 * Returns a new snapshot (does NOT mutate input).
 */
export function applyWSEvent(snapshot: PipelineSnapshot, event: WSEvent): PipelineSnapshot {
  // Shallow-clone with new objects for mutated maps
  const snap: PipelineSnapshot = {
    ...snapshot,
    run_status: { ...snapshot.run_status },
    stage_statuses: { ...snapshot.stage_statuses },
    artifact_statuses: { ...snapshot.artifact_statuses },
  };

  switch (event.type) {
    case 'stage_started': {
      const key = stageKey(event.stage_key, event.component_key);
      snap.stage_statuses[key] = 'running';
      snap.is_running = true;
      snap.is_paused = false;
      snap.paused_stage = null;
      break;
    }

    case 'stage_progress':
      // Progress events don't change status
      break;

    case 'stage_awaiting_review': {
      const key = stageKey(event.stage_key, event.component_key);
      snap.stage_statuses[key] = 'awaiting_review';
      if (event.artifact_id) {
        snap.artifact_statuses[event.artifact_id] = 'awaiting_review';
      }
      break;
    }

    case 'stage_completed': {
      const key = stageKey(event.stage_key, event.component_key);
      const status = event.status || 'approved';
      snap.stage_statuses[key] = status;
      if (event.artifact_id) {
        snap.artifact_statuses[event.artifact_id] = status;
      }
      break;
    }

    case 'stage_failed': {
      const key = stageKey(event.stage_key, event.component_key);
      snap.stage_statuses[key] = 'failed';
      if (event.artifact_id) {
        // Preserve artifact status if it was already reviewed — a stage
        // failure (e.g. cancellation) shouldn't nuke a valid artifact.
        const current = snapshot.artifact_statuses[event.artifact_id];
        if (current !== 'approved' && current !== 'awaiting_review') {
          snap.artifact_statuses[event.artifact_id] = event.artifact_status || 'pending';
        }
      }
      break;
    }

    case 'pipeline_completed':
      snap.is_running = false;
      snap.is_paused = false;
      snap.paused_stage = null;
      if (event.run_id) {
        snap.run_status[event.run_id] = 'completed';
      }
      break;

    case 'pipeline_cancelled':
      snap.is_running = false;
      snap.is_paused = false;
      snap.paused_stage = null;
      break;

    case 'pipeline_paused':
      snap.is_paused = true;
      snap.paused_stage = event.stage_key;
      if (event.run_id) {
        snap.run_status[event.run_id] = 'paused';
      }
      break;

    case 'staleness_propagated':
      for (const aid of event.stale_artifact_ids) {
        snap.artifact_statuses[aid] = 'stale';
      }
      break;

    case 'feedback_saved':
      // Feedback doesn't change status
      break;

    case 'cascade_completed':
      snap.is_running = false;
      if (event.run_id) {
        snap.run_status[event.run_id] = 'completed';
      }
      break;

    case 'artifact_pruned':
      delete snap.artifact_statuses[event.artifact_id];
      break;

    case 'comment_added':
    case 'comment_updated':
    case 'comment_deleted':
      // Comment events don't affect pipeline status
      break;
  }

  return snap;
}

function stageKey(stage: string, component?: string): string {
  return component ? `${stage}/${component}` : stage;
}

/**
 * Find the most relevant execution for a stage_key/component_key pair.
 * Prefers non-terminal statuses (running > awaiting_review > others).
 */
function findExecution(
  executions: StageExecution[],
  stageKey: string,
  componentKey?: string,
): number {
  let bestIdx = -1;
  for (let i = 0; i < executions.length; i++) {
    const e = executions[i];
    if (e.stage_key !== stageKey) continue;
    if (componentKey !== undefined && e.component_key !== (componentKey || null)) continue;
    if (bestIdx === -1) { bestIdx = i; continue; }
    // Prefer active executions over terminal ones
    const active = new Set(['running', 'ai_review', 'pending', 'awaiting_review']);
    if (active.has(e.status) && !active.has(executions[bestIdx].status)) {
      bestIdx = i;
    }
  }
  return bestIdx;
}

/**
 * Patch executions array based on a WS event. Returns the original array
 * unchanged if no patch is needed (callers can use referential equality
 * to skip unnecessary store updates).
 */
export function patchExecutions(executions: StageExecution[], event: WSEvent): StageExecution[] {
  switch (event.type) {
    case 'stage_started': {
      const idx = findExecution(executions, event.stage_key, event.component_key);
      if (idx === -1) return executions;
      const updated = [...executions];
      updated[idx] = { ...updated[idx], status: 'running' as StageExecutionStatus };
      return updated;
    }

    case 'stage_awaiting_review': {
      const idx = findExecution(executions, event.stage_key, event.component_key);
      if (idx === -1) return executions;
      const updated = [...executions];
      updated[idx] = {
        ...updated[idx],
        status: 'awaiting_review' as StageExecutionStatus,
        artifact_id: event.artifact_id ?? updated[idx].artifact_id,
      };
      return updated;
    }

    case 'stage_completed': {
      const idx = findExecution(executions, event.stage_key, event.component_key);
      if (idx === -1) return executions;
      const status = (event.status || 'approved') as StageExecutionStatus;
      const updated = [...executions];
      updated[idx] = {
        ...updated[idx],
        status,
        artifact_id: event.artifact_id ?? updated[idx].artifact_id,
      };
      return updated;
    }

    case 'stage_failed': {
      const idx = findExecution(executions, event.stage_key, event.component_key);
      if (idx === -1) return executions;
      const updated = [...executions];
      updated[idx] = {
        ...updated[idx],
        status: 'failed' as StageExecutionStatus,
        error_message: event.error ?? updated[idx].error_message,
      };
      return updated;
    }

    default:
      return executions;
  }
}
