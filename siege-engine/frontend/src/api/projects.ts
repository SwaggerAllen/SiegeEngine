import api from './client';
import type { Artifact, Project, ProjectDetail } from '../types/project';

export async function listProjects(): Promise<Project[]> {
  const { data } = await api.get('/projects/');
  return data;
}

export async function getProject(id: string): Promise<ProjectDetail> {
  const { data } = await api.get(`/projects/${id}`);
  return data;
}

export async function createProject(
  name: string,
  description: string | null,
  projectDocContent: string
): Promise<Project> {
  const { data } = await api.post('/projects/', {
    name,
    description,
    project_doc_content: projectDocContent,
  });
  return data;
}

export async function updateProject(
  id: string,
  updates: { name?: string; description?: string }
): Promise<Project> {
  const { data } = await api.put(`/projects/${id}`, updates);
  return data;
}

export async function deleteProject(id: string): Promise<void> {
  await api.delete(`/projects/${id}`);
}

export async function getArtifact(artifactId: string): Promise<Artifact> {
  const { data } = await api.get(`/projects/artifacts/${artifactId}`);
  return data;
}

export async function updateArtifact(
  artifactId: string,
  content: string
): Promise<Artifact> {
  const { data } = await api.put(`/projects/artifacts/${artifactId}`, { content });
  return data;
}

export async function getArtifactDiff(artifactId: string) {
  const { data } = await api.get(`/projects/artifacts/${artifactId}/diff`);
  return data;
}

export interface ArtifactVersion {
  sha: string;
  message: string;
  timestamp: string;
}

export async function getArtifactHistory(artifactId: string): Promise<ArtifactVersion[]> {
  const { data } = await api.get(`/projects/artifacts/${artifactId}/history`);
  return data;
}

export async function getArtifactVersion(
  artifactId: string,
  commitSha: string
): Promise<{ content: string; sha: string }> {
  const { data } = await api.get(`/projects/artifacts/${artifactId}/versions/${commitSha}`);
  return data;
}
