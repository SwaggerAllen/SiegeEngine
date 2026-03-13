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

export interface StageExecution {
  id: string;
  stage_key: string;
  component_key: string | null;
  status: string;
  artifact_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  run_id: string;
}

export interface PipelineStartOptions {
  human_review?: boolean;
  ai_loops?: number;
  stop_point?: string;
}

export interface PipelineRun {
  id: string;
  run_number: number;
  run_id: string;
  status: string;
  human_review: boolean;
  ai_loops: number;
  stop_point: string;
  git_commit_sha: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export type WSEvent =
  | { type: 'stage_started'; stage_key: string; component_key?: string }
  | { type: 'stage_progress'; stage_key: string; step: string; component_key?: string; message: string }
  | { type: 'stage_awaiting_review'; stage_key: string; component_key?: string; artifact_id: string }
  | { type: 'stage_completed'; stage_key: string; component_key?: string; artifact_id?: string; status?: string }
  | { type: 'stage_failed'; stage_key: string; component_key?: string; error: string }
  | { type: 'pipeline_completed'; run_id: string; run_number?: number; git_commit_sha?: string }
  | { type: 'pipeline_paused'; stage_key: string; run_id: string; message?: string }
  | { type: 'staleness_propagated'; stale_artifact_ids: string[] }
  | { type: 'feedback_saved'; stage_key: string; component_key?: string; execution_id: string; artifact_id?: string };
