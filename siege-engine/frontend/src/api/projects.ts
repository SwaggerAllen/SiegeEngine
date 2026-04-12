import { z } from 'zod';
import api from './client';
import { ProjectSchema, ProjectDetailSchema } from '../schemas/project';
import type { Project, ProjectDetail } from '../types/project';

export async function listProjects(): Promise<Project[]> {
  const { data } = await api.get('/projects/');
  return z.array(ProjectSchema).parse(data);
}

export async function getProject(id: string): Promise<ProjectDetail> {
  const { data } = await api.get(`/projects/${id}`);
  return ProjectDetailSchema.parse(data);
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
  return ProjectSchema.parse(data);
}

export async function updateProject(
  id: string,
  updates: { name?: string; description?: string }
): Promise<Project> {
  const { data } = await api.put(`/projects/${id}`, updates);
  return ProjectSchema.parse(data);
}

export async function deleteProject(id: string): Promise<void> {
  await api.delete(`/projects/${id}`);
}

export async function cloneProject(id: string, newName?: string): Promise<Project> {
  const { data } = await api.post(`/projects/${id}/clone`, { new_name: newName ?? null });
  return ProjectSchema.parse(data);
}
