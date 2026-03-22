/**
 * Pure reducer for pipeline event sourcing.
 * Mirrors backend/pipeline/reducer.py — apply WS events to a local snapshot.
 */

import type { PipelineSnapshot, WSEvent } from '../types/pipeline';

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
        snap.artifact_statuses[event.artifact_id] = event.artifact_status || 'pending';
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
