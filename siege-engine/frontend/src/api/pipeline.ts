import api from './client';
import type { PipelineConfig, PipelineRun, PipelineSnapshot, PipelineStartOptions, StageDefinition } from '../types/pipeline';

export async function getPipelineConfig(projectId: string): Promise<PipelineConfig> {
  const { data } = await api.get(`/pipeline/${projectId}/config`);
  return data;
}

export async function updatePipelineConfig(
  projectId: string,
  updates: { execution_mode?: string; default_model?: string; default_temperature?: number }
): Promise<PipelineConfig> {
  const { data } = await api.put(`/pipeline/${projectId}/config`, updates);
  return data;
}

export async function startPipeline(
  projectId: string,
  options?: PipelineStartOptions
) {
  const { data } = await api.post(`/pipeline/${projectId}/start`, options || {});
  return data;
}

export async function resumeRun(
  projectId: string,
  options?: PipelineStartOptions
) {
  const { data } = await api.post(`/pipeline/${projectId}/resume-run`, options || {});
  return data;
}

export async function listRuns(projectId: string): Promise<PipelineRun[]> {
  const { data } = await api.get(`/pipeline/${projectId}/runs`);
  return data;
}

export async function getRunState(projectId: string, runNumber: number) {
  const { data } = await api.get(`/pipeline/${projectId}/runs/${runNumber}/state`);
  return data;
}

export async function resumeStage(
  projectId: string,
  executionId: string,
  action: string,
  notes?: string,
  editedContent?: string
) {
  const { data } = await api.post(`/pipeline/${projectId}/resume`, {
    execution_id: executionId,
    action,
    notes,
    edited_content: editedContent,
  });
  return data;
}

export async function reviseArtifact(
  projectId: string,
  artifactId: string,
  feedback: string
) {
  const { data } = await api.post(`/pipeline/${projectId}/revise`, {
    artifact_id: artifactId,
    feedback,
  });
  return data;
}

export async function resolveStale(
  projectId: string,
  artifactId: string,
  action: string,
  notes?: string,
  editedContent?: string
) {
  const { data } = await api.post(`/pipeline/${projectId}/resolve-stale`, {
    artifact_id: artifactId,
    action,
    notes,
    edited_content: editedContent,
  });
  return data;
}

export async function regenDownstream(
  projectId: string,
  artifactId: string,
) {
  const { data } = await api.post(`/pipeline/${projectId}/regen-downstream`, {
    artifact_id: artifactId,
  });
  return data;
}

export async function regenerateArtifacts(
  projectId: string,
  artifactIds: string[]
) {
  const { data } = await api.post(`/pipeline/${projectId}/regenerate`, {
    artifact_ids: artifactIds,
  });
  return data;
}

export async function getPipelineStatus(projectId: string) {
  const { data } = await api.get(`/pipeline/${projectId}/status`);
  return data;
}

export async function getSnapshot(projectId: string): Promise<PipelineSnapshot> {
  const { data } = await api.get(`/pipeline/${projectId}/snapshot`);
  return data;
}

export async function cancelPipeline(
  projectId: string,
  options?: { open_pr?: boolean; pr_title?: string; pr_body?: string; base_branch?: string }
) {
  const { data } = await api.post(`/pipeline/${projectId}/cancel`, options || {});
  return data;
}

export async function resetAll(projectId: string) {
  const { data } = await api.post(`/pipeline/${projectId}/reset-all`);
  return data;
}

export async function getBlockingPR(projectId: string) {
  const { data } = await api.get(`/pipeline/${projectId}/blocking-pr`);
  return data as { blocking_pr_url: string | null; blocking_pr_number: number | null };
}

export async function checkBlockingPR(projectId: string) {
  const { data } = await api.post(`/pipeline/${projectId}/blocking-pr/check`);
  return data as { blocking: boolean; pr_state?: string; blocking_pr_url?: string; blocking_pr_number?: number };
}

export async function dismissBlockingPR(projectId: string) {
  const { data } = await api.post(`/pipeline/${projectId}/blocking-pr/dismiss`);
  return data;
}

export async function retryStage(projectId: string, executionId: string) {
  const { data } = await api.post(`/pipeline/${projectId}/retry/${executionId}`);
  return data;
}

export async function cancelStage(projectId: string, executionId: string) {
  const { data } = await api.post(`/pipeline/${projectId}/cancel-stage/${executionId}`);
  return data;
}

export async function forceRestartStage(projectId: string, executionId: string) {
  const { data } = await api.post(`/pipeline/${projectId}/force-restart/${executionId}`);
  return data;
}

export async function triggerStage(
  projectId: string,
  stageKey: string,
  componentKey?: string | null
) {
  const { data } = await api.post(`/pipeline/${projectId}/trigger-stage`, {
    stage_key: stageKey,
    component_key: componentKey ?? null,
  });
  return data;
}

export async function pruneArtifact(projectId: string, artifactId: string) {
  const { data } = await api.delete(`/pipeline/${projectId}/prune/${artifactId}`);
  return data;
}

export async function reparseFanout(projectId: string, artifactId: string): Promise<{
  added: string[];
  removed: string[];
  total: number;
}> {
  const { data } = await api.post(`/pipeline/${projectId}/artifacts/${artifactId}/reparse`);
  return data;
}

export interface ArtifactDiff {
  diff: string;
  from_version: number;
  to_version: number;
  from_sha: string;
  to_sha: string;
}

export async function getArtifactDiff(projectId: string, artifactId: string): Promise<ArtifactDiff> {
  const { data } = await api.get(`/pipeline/${projectId}/artifacts/${artifactId}/diff`);
  return data;
}

export async function getDAG(projectId: string) {
  const { data } = await api.get(`/dag/${projectId}`);
  return data;
}

export async function getDocumentsDAG(projectId: string) {
  const { data } = await api.get(`/dag/${projectId}/documents`);
  return data;
}

export async function getStaleArtifacts(projectId: string) {
  const { data } = await api.get(`/dag/${projectId}/stale`);
  return data;
}

export interface ComponentInfo {
  key: string;
  name: string;
  description: string | null;
  dependencies: string[];
  dependents: string[];
  change: 'new' | 'existing' | 'removed' | null;
}

export async function getComponents(projectId: string): Promise<ComponentInfo[]> {
  const { data } = await api.get(`/dag/${projectId}/components`);
  return data;
}

export async function updateStageConfig(
  projectId: string,
  stageKey: string,
  updates: Partial<Pick<StageDefinition, 'display_name' | 'model_override' | 'temperature_override' | 'ai_review_enabled' | 'human_review_enabled'>>
): Promise<StageDefinition> {
  const { data } = await api.put(`/pipeline/${projectId}/stages/${stageKey}`, updates);
  return data;
}

export async function resetStageConfig(
  projectId: string,
  stageKey: string
): Promise<StageDefinition> {
  const { data } = await api.post(`/pipeline/${projectId}/stages/${stageKey}/reset`);
  return data;
}

export interface ReconcileResult {
  corrections: Array<Record<string, unknown>>;
  orphans_removed: Array<Record<string, unknown>>;
  run_id: string;
  run_number: number;
}

export async function reconcilePipeline(projectId: string): Promise<ReconcileResult> {
  const { data } = await api.post(`/pipeline/${projectId}/reconcile`);
  return data;
}

export interface PromptPreviewMessage {
  role: string;
  content: string;
}

export interface PromptPreview {
  messages: PromptPreviewMessage[];
  model: string;
  temperature: number;
}

export async function getPromptPreview(
  projectId: string,
  artifactId: string,
  humanNotes?: string,
): Promise<PromptPreview> {
  const { data } = await api.post(`/pipeline/${projectId}/prompt-preview`, {
    artifact_id: artifactId,
    human_notes: humanNotes ?? null,
  });
  return data;
}
