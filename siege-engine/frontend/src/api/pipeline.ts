import { z } from 'zod';
import api from './client';
import { debugLog, debugError } from '../lib/debugLog';
import {
  PipelineConfigSchema,
  PipelineEventPageSchema,
  PipelineRunSchema,
  PipelineSnapshotSchema,
  StageDefinitionSchema,
} from '../schemas/pipeline';
import { DAGResponseSchema } from '../schemas/dag';
import type { PipelineConfig, PipelineEventPage, PipelineRun, PipelineSnapshot, PipelineStartOptions, StageDefinition } from '../types/pipeline';
import type { DAGResponse } from '../types/dag';

// ──── Unified action helper ────

async function pipelineAction(projectId: string, action: Record<string, unknown>) {
  const { data } = await api.post(`/pipeline/${projectId}/action`, action);
  return data;
}

// ──── Config (CRUD — stays as REST) ────

export async function getPipelineConfig(projectId: string): Promise<PipelineConfig> {
  const { data } = await api.get(`/pipeline/${projectId}/config`);
  return PipelineConfigSchema.parse(data);
}

export async function updatePipelineConfig(
  projectId: string,
  updates: { execution_mode?: string; default_model?: string; default_temperature?: number }
): Promise<PipelineConfig> {
  const { data } = await api.put(`/pipeline/${projectId}/config`, updates);
  return PipelineConfigSchema.parse(data);
}

// ──── Pipeline lifecycle (via /action) ────

export async function startPipeline(
  projectId: string,
  options?: PipelineStartOptions
) {
  return pipelineAction(projectId, { type: 'start', ...options });
}

export async function resumeRun(
  projectId: string,
  options?: PipelineStartOptions
) {
  return pipelineAction(projectId, { type: 'resume_run', ...options });
}

export async function cancelPipeline(
  projectId: string,
  options?: { open_pr?: boolean; pr_title?: string; pr_body?: string; base_branch?: string }
) {
  return pipelineAction(projectId, { type: 'cancel', ...options });
}

export async function resetAll(projectId: string) {
  return pipelineAction(projectId, { type: 'reset_all' });
}

// ──── Reads (stay as individual GETs) ────

export async function listRuns(projectId: string): Promise<PipelineRun[]> {
  const { data } = await api.get(`/pipeline/${projectId}/runs`);
  return z.array(PipelineRunSchema).parse(data);
}

export async function getRunState(projectId: string, runNumber: number) {
  const { data } = await api.get(`/pipeline/${projectId}/runs/${runNumber}/state`);
  return data;
}

export async function getPipelineStatus(projectId: string) {
  const { data } = await api.get(`/pipeline/${projectId}/status`);
  return data;
}

export async function getSnapshot(projectId: string): Promise<PipelineSnapshot> {
  // Snapshot is now served by /status — extract snapshot portion
  const { data } = await api.get(`/pipeline/${projectId}/status`);
  return PipelineSnapshotSchema.parse(data.snapshot);
}

export async function getDebugState(projectId: string) {
  const { data } = await api.get(`/pipeline/${projectId}/debug-state`);
  return data;
}

export async function getBlockingPR(projectId: string) {
  const { data } = await api.get(`/pipeline/${projectId}/blocking-pr`);
  return data as { blocking_pr_url: string | null; blocking_pr_number: number | null };
}

// ──── Stage actions (via /action) ────

export async function resumeStage(
  projectId: string,
  executionId: string,
  action: string,
  notes?: string,
  editedContent?: string
) {
  return pipelineAction(projectId, {
    type: 'resume_stage',
    execution_id: executionId,
    action,
    notes,
    edited_content: editedContent,
  });
}

export async function reviseArtifact(
  projectId: string,
  artifactId: string,
  feedback: string
) {
  return pipelineAction(projectId, {
    type: 'revise',
    artifact_id: artifactId,
    feedback,
  });
}

export async function resolveStale(
  projectId: string,
  artifactId: string,
  action: string,
  notes?: string,
  editedContent?: string
) {
  return pipelineAction(projectId, {
    type: 'resolve_stale',
    artifact_id: artifactId,
    action,
    notes,
    edited_content: editedContent,
  });
}

export async function regenDownstream(
  projectId: string,
  artifactId: string,
) {
  return pipelineAction(projectId, {
    type: 'regen_downstream',
    artifact_id: artifactId,
  });
}

export async function regenerateArtifacts(
  projectId: string,
  artifactIds: string[]
) {
  return pipelineAction(projectId, {
    type: 'regenerate',
    artifact_ids: artifactIds,
  });
}

export async function retryStage(projectId: string, executionId: string) {
  return pipelineAction(projectId, { type: 'retry', execution_id: executionId });
}

export async function cancelStage(projectId: string, executionId: string) {
  return pipelineAction(projectId, { type: 'cancel_stage', execution_id: executionId });
}

export async function forceRestartStage(projectId: string, executionId: string) {
  return pipelineAction(projectId, { type: 'force_restart', execution_id: executionId });
}

export async function triggerStage(
  projectId: string,
  stageKey: string,
  componentKey?: string | null
) {
  return pipelineAction(projectId, {
    type: 'trigger_stage',
    stage_key: stageKey,
    component_key: componentKey ?? null,
  });
}

export async function pruneArtifact(projectId: string, artifactId: string) {
  return pipelineAction(projectId, { type: 'prune', artifact_id: artifactId });
}

export async function reparseFanout(projectId: string, artifactId: string): Promise<{
  added: string[];
  removed: string[];
  total: number;
}> {
  return pipelineAction(projectId, { type: 'reparse', artifact_id: artifactId });
}

// ──── Blocking PR (via /action) ────

export async function checkBlockingPR(projectId: string) {
  return pipelineAction(projectId, { type: 'check_blocking_pr' }) as Promise<{
    blocking: boolean; pr_state?: string; blocking_pr_url?: string; blocking_pr_number?: number
  }>;
}

export async function dismissBlockingPR(projectId: string) {
  return pipelineAction(projectId, { type: 'dismiss_blocking_pr' });
}

// ──── Artifact reads ────

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

// ──── Events ────

export async function listEvents(
  projectId: string,
  params?: { run_id?: string; event_type?: string; limit?: number; offset?: number }
): Promise<PipelineEventPage> {
  const { data } = await api.get(`/pipeline/${projectId}/events`, { params });
  return PipelineEventPageSchema.parse(data);
}

export async function getSnapshotAtSequence(
  projectId: string,
  sequence: number
): Promise<PipelineSnapshot> {
  const { data } = await api.get(`/pipeline/${projectId}/events/snapshot-at/${sequence}`);
  return PipelineSnapshotSchema.parse(data);
}

export async function revertToSequence(
  projectId: string,
  sequence: number
): Promise<{ status: string; reverted_to_sequence: number; events_deleted: number; artifacts_restored: number; artifacts_deleted: number }> {
  return pipelineAction(projectId, { type: 'revert', sequence });
}

// ──── Prompt preview (via /action) ────

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
  return pipelineAction(projectId, {
    type: 'prompt_preview',
    artifact_id: artifactId,
    human_notes: humanNotes ?? null,
  });
}

// ──── Admin / recovery (via /action) ────

export interface ReconcileResult {
  corrections: Array<Record<string, unknown>>;
  orphans_removed: Array<Record<string, unknown>>;
  run_id: string;
  run_number: number;
}

export async function reconcilePipeline(projectId: string): Promise<ReconcileResult> {
  return pipelineAction(projectId, { type: 'reconcile' });
}

// ──── DAG (separate router, stays as REST) ────

export async function getDAG(projectId: string): Promise<DAGResponse> {
  debugLog('api.getDAG', `fetching ${projectId}`);
  try {
    const { data } = await api.get(`/dag/${projectId}`);
    const result = DAGResponseSchema.safeParse(data);
    if (!result.success) {
      debugLog('api.getDAG', `schema fail: ${JSON.stringify(result.error.issues).slice(0, 200)}`);
      return { nodes: [], edges: [] };
    }
    debugLog('api.getDAG', `ok: ${result.data.nodes.length} nodes, ${result.data.edges.length} edges`);
    return result.data;
  } catch (err) {
    debugError('api.getDAG', err);
    throw err;
  }
}

export async function getDocumentsDAG(projectId: string): Promise<DAGResponse> {
  debugLog('api.getDocsDAG', `fetching ${projectId}`);
  try {
    const { data } = await api.get(`/dag/${projectId}/documents`);
    const result = DAGResponseSchema.safeParse(data);
    if (!result.success) {
      debugLog('api.getDocsDAG', `schema fail: ${JSON.stringify(result.error.issues).slice(0, 200)}`);
      return { nodes: [], edges: [] };
    }
    debugLog('api.getDocsDAG', `ok: ${result.data.nodes.length} nodes, ${result.data.edges.length} edges`);
    return result.data;
  } catch (err) {
    debugError('api.getDocsDAG', err);
    throw err;
  }
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

// ──── Stage config (CRUD — stays as REST) ────

export async function updateStageConfig(
  projectId: string,
  stageKey: string,
  updates: Partial<Pick<StageDefinition, 'display_name' | 'model_override' | 'temperature_override' | 'ai_review_enabled' | 'human_review_enabled'>>
): Promise<StageDefinition> {
  const { data } = await api.put(`/pipeline/${projectId}/stages/${stageKey}`, updates);
  return StageDefinitionSchema.parse(data);
}

export async function resetStageConfig(
  projectId: string,
  stageKey: string
): Promise<StageDefinition> {
  const { data } = await api.post(`/pipeline/${projectId}/stages/${stageKey}/reset`);
  return StageDefinitionSchema.parse(data);
}
