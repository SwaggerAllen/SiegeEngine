import api from './client';
import type { PipelineConfig } from '../types/pipeline';

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
  executionMode?: string
) {
  const { data } = await api.post(`/pipeline/${projectId}/start`, {
    execution_mode: executionMode,
  });
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

export async function cancelPipeline(projectId: string) {
  const { data } = await api.post(`/pipeline/${projectId}/cancel`);
  return data;
}

export async function getDAG(projectId: string) {
  const { data } = await api.get(`/dag/${projectId}`);
  return data;
}

export async function getStaleArtifacts(projectId: string) {
  const { data } = await api.get(`/dag/${projectId}/stale`);
  return data;
}
