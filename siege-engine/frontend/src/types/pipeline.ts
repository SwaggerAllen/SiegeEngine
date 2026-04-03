export type {
  StageDefinition,
  PipelineConfig,
  StageExecutionStatus,
  StageExecution,
  PipelineRunStatus,
  PipelineRun,
  PipelineSnapshot,
  PipelineEvent,
  PipelineEventPage,
  WSEvent,
  PipelineStartOptions,
} from '../schemas/pipeline';

/** Execution statuses that allow a force-restart action. */
export const RESTARTABLE_STATUSES: ReadonlySet<string> = new Set<string>([
  'running', 'ai_review', 'failed',
]);
