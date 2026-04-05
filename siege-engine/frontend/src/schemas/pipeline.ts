import { z } from 'zod';

// --- Stage & Config ---

export const StageDefinitionSchema = z.object({
  id: z.string(),
  stage_key: z.string(),
  display_name: z.string(),
  order_index: z.number(),
  output_artifact_type: z.string(),
  input_stage_keys: z.array(z.string()),
  fan_out_strategy: z.string(),
  ai_review_enabled: z.boolean(),
  human_review_enabled: z.boolean(),
  prompt_template_key: z.string(),
  model_override: z.string().nullable(),
  temperature_override: z.number().nullable(),
});

export const PipelineConfigSchema = z.object({
  id: z.string(),
  execution_mode: z.string(),
  default_model: z.string(),
  default_temperature: z.number(),
  stages: z.array(StageDefinitionSchema),
});

// --- Execution ---

export const StageExecutionStatusSchema = z.enum([
  'pending', 'running', 'awaiting_review', 'approved', 'rejected', 'failed', 'ai_review',
]);

export const StageExecutionSchema = z.object({
  id: z.string(),
  stage_key: z.string(),
  component_key: z.string().nullable(),
  status: StageExecutionStatusSchema,
  artifact_id: z.string().nullable(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  error_message: z.string().nullable(),
  run_id: z.string(),
});

// --- Run ---

export const PipelineRunStatusSchema = z.enum([
  'running', 'completed', 'cancelled', 'failed', 'paused',
]);

export const PipelineRunSchema = z.object({
  id: z.string(),
  run_number: z.number(),
  run_id: z.string(),
  status: PipelineRunStatusSchema,
  ai_loops: z.number(),
  stop_point: z.string(),
  start_stage_key: z.string().nullable(),
  start_component_key: z.string().nullable(),
  git_commit_sha: z.string().nullable(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
});

// --- Snapshot ---

export const PipelineSnapshotSchema = z.object({
  is_running: z.boolean(),
  is_paused: z.boolean(),
  paused_stage: z.string().nullable(),
  current_run_id: z.string().nullable(),
  stage_statuses: z.record(z.string(), z.string()),
  artifact_statuses: z.record(z.string(), z.string()),
  run_status: z.record(z.string(), z.string()),
  last_sequence: z.number(),
  artifact_versions: z.record(z.string(), z.number()).optional(),
  stage_errors: z.record(z.string(), z.object({
    error: z.string().optional(),
    retry_count: z.number().optional(),
  })).optional(),
  comment_counts: z.record(z.string(), z.number()).optional(),
  stage_triggers: z.record(z.string(), z.string()).optional(),
  artifact_meta: z.record(z.string(), z.object({
    type: z.string().optional(),
    name: z.string().optional(),
  })).optional(),
  artifact_git_shas: z.record(z.string(), z.string()).optional(),
  cascade_parents: z.record(z.string(), z.string()).optional(),
  artifact_stale: z.record(z.string(), z.boolean()).optional(),
});

// --- Events ---

export const PipelineEventSchema = z.object({
  id: z.string(),
  sequence: z.number(),
  event_type: z.string(),
  payload: z.record(z.string(), z.unknown()),
  run_id: z.string().nullable(),
  created_at: z.string().nullable(),
});

export const PipelineEventPageSchema = z.object({
  events: z.array(PipelineEventSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
  artifact_names: z.record(z.string(), z.string()),
  run_numbers: z.record(z.string(), z.number()),
});

// --- WebSocket events (discriminated union) ---

export const WSEventSchema = z.discriminatedUnion('type', [
  z.object({ type: z.literal('stage_started'), stage_key: z.string(), component_key: z.string().optional() }),
  z.object({ type: z.literal('stage_progress'), stage_key: z.string(), step: z.string(), component_key: z.string().optional(), artifact_id: z.string().optional(), message: z.string() }),
  z.object({ type: z.literal('stage_awaiting_review'), stage_key: z.string(), component_key: z.string().optional(), artifact_id: z.string() }),
  z.object({ type: z.literal('stage_completed'), stage_key: z.string(), component_key: z.string().optional(), artifact_id: z.string().optional(), status: z.string().optional() }),
  z.object({ type: z.literal('stage_failed'), stage_key: z.string(), component_key: z.string().optional(), error: z.string(), artifact_id: z.string().optional(), artifact_status: z.string().optional() }),
  z.object({ type: z.literal('pipeline_completed'), run_id: z.string(), run_number: z.number().optional(), git_commit_sha: z.string().optional() }),
  z.object({ type: z.literal('pipeline_cancelled'), cancelled_count: z.number() }),
  z.object({ type: z.literal('pipeline_paused'), stage_key: z.string(), run_id: z.string(), message: z.string().optional() }),
  z.object({ type: z.literal('staleness_propagated'), stale_artifact_ids: z.array(z.string()) }),
  z.object({ type: z.literal('feedback_saved'), stage_key: z.string(), component_key: z.string().optional(), execution_id: z.string(), artifact_id: z.string().optional() }),
  z.object({ type: z.literal('comment_added'), artifact_id: z.string(), comment_id: z.string().optional() }),
  z.object({ type: z.literal('comment_updated'), artifact_id: z.string(), comment_id: z.string() }),
  z.object({ type: z.literal('comment_deleted'), artifact_id: z.string(), comment_id: z.string() }),
  z.object({ type: z.literal('artifact_pruned'), artifact_id: z.string() }),
  z.object({ type: z.literal('cascade_completed'), run_id: z.string().optional() }),
  z.object({ type: z.literal('summary_started'), artifact_id: z.string() }),
  z.object({ type: z.literal('summary_completed'), artifact_id: z.string() }),
  z.object({ type: z.literal('summary_failed'), artifact_id: z.string() }),
  z.object({ type: z.literal('log_entry'), timestamp: z.string(), level: z.string(), logger: z.string(), message: z.string() }),
]);

// --- Start options ---

export const PipelineStartOptionsSchema = z.object({
  ai_loops: z.number().optional(),
  stop_point: z.string().optional(),
  start_stage_key: z.string().nullable().optional(),
  start_component_key: z.string().nullable().optional(),
});

// --- Inferred types ---

export type StageDefinition = z.infer<typeof StageDefinitionSchema>;
export type PipelineConfig = z.infer<typeof PipelineConfigSchema>;
export type StageExecutionStatus = z.infer<typeof StageExecutionStatusSchema>;
export type StageExecution = z.infer<typeof StageExecutionSchema>;
export type PipelineRunStatus = z.infer<typeof PipelineRunStatusSchema>;
export type PipelineRun = z.infer<typeof PipelineRunSchema>;
export type PipelineSnapshot = z.infer<typeof PipelineSnapshotSchema>;
export type PipelineEvent = z.infer<typeof PipelineEventSchema>;
export type PipelineEventPage = z.infer<typeof PipelineEventPageSchema>;
export type WSEvent = z.infer<typeof WSEventSchema>;
export type PipelineStartOptions = z.infer<typeof PipelineStartOptionsSchema>;
