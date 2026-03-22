export interface StageDefinition {
  id: string;
  stage_key: string;
  display_name: string;
  order_index: number;
  output_artifact_type: string;
  input_stage_keys: string[];
  fan_out_strategy: string;
  ai_review_enabled: boolean;
  human_review_enabled: boolean;
  prompt_template_key: string;
  model_override: string | null;
  temperature_override: number | null;
}

export interface PipelineConfig {
  id: string;
  execution_mode: string;
  default_model: string;
  default_temperature: number;
  stages: StageDefinition[];
}

export type StageExecutionStatus = 'pending' | 'running' | 'awaiting_review' | 'approved' | 'rejected' | 'failed' | 'ai_review';

/** Execution statuses that allow a force-restart action. */
export const RESTARTABLE_STATUSES: ReadonlySet<string> = new Set<string>([
  'running', 'ai_review', 'failed', 'rejected',
]);

export interface StageExecution {
  id: string;
  stage_key: string;
  component_key: string | null;
  status: StageExecutionStatus;
  artifact_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  run_id: string;
}

export interface PipelineStartOptions {
  ai_loops?: number;
  stop_point?: string;
  start_stage_key?: string | null;
  start_component_key?: string | null;
}

export type PipelineRunStatus = 'running' | 'completed' | 'cancelled' | 'failed' | 'paused';

export interface PipelineRun {
  id: string;
  run_number: number;
  run_id: string;
  status: PipelineRunStatus;
  ai_loops: number;
  stop_point: string;
  start_stage_key: string | null;
  start_component_key: string | null;
  git_commit_sha: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface PipelineSnapshot {
  is_running: boolean;
  is_paused: boolean;
  paused_stage: string | null;
  current_run_id: string | null;
  stage_statuses: Record<string, string>;
  artifact_statuses: Record<string, string>;
  run_status: Record<string, string>;
  last_sequence: number;
  // Extended snapshot fields
  artifact_versions?: Record<string, number>;
  stage_errors?: Record<string, { error?: string; retry_count?: number }>;
  comment_counts?: Record<string, number>;
  stage_triggers?: Record<string, string>;
  artifact_meta?: Record<string, { type?: string; name?: string }>;
  artifact_git_shas?: Record<string, string>;
  cascade_parents?: Record<string, string>;
}

export interface PipelineEvent {
  id: string;
  sequence: number;
  event_type: string;
  payload: Record<string, unknown>;
  run_id: string | null;
  created_at: string | null;
}

export interface PipelineEventPage {
  events: PipelineEvent[];
  total: number;
  limit: number;
  offset: number;
  artifact_names: Record<string, string>;
  run_numbers: Record<string, number>;
}

export type WSEvent =
  | { type: 'stage_started'; stage_key: string; component_key?: string }
  | { type: 'stage_progress'; stage_key: string; step: string; component_key?: string; message: string }
  | { type: 'stage_awaiting_review'; stage_key: string; component_key?: string; artifact_id: string }
  | { type: 'stage_completed'; stage_key: string; component_key?: string; artifact_id?: string; status?: string }
  | { type: 'stage_failed'; stage_key: string; component_key?: string; error: string; artifact_id?: string; artifact_status?: string }
  | { type: 'pipeline_completed'; run_id: string; run_number?: number; git_commit_sha?: string }
  | { type: 'pipeline_cancelled'; cancelled_count: number }
  | { type: 'pipeline_paused'; stage_key: string; run_id: string; message?: string }
  | { type: 'staleness_propagated'; stale_artifact_ids: string[] }
  | { type: 'feedback_saved'; stage_key: string; component_key?: string; execution_id: string; artifact_id?: string }
  | { type: 'comment_added'; artifact_id: string; comment_id?: string }
  | { type: 'comment_updated'; artifact_id: string; comment_id: string }
  | { type: 'comment_deleted'; artifact_id: string; comment_id: string }
  | { type: 'artifact_pruned'; artifact_id: string }
  | { type: 'cascade_completed'; run_id?: string }
  | { type: 'log_entry'; timestamp: string; level: string; logger: string; message: string };
