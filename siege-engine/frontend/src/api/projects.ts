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
  projectDocContent: string,
  remoteUrl?: string | null,
  githubRepoSlug?: string | null,
): Promise<Project> {
  const { data } = await api.post('/projects/', {
    name,
    description,
    project_doc_content: projectDocContent,
    // null-vs-undefined matters at the wire — the backend treats
    // omitted fields as "leave unset". Send undefined when blank so
    // the JSON envelope drops the key entirely.
    remote_url: remoteUrl || undefined,
    github_repo_slug: githubRepoSlug || undefined,
  });
  return ProjectSchema.parse(data);
}

export async function importProject(
  name: string,
  description: string | null,
  file: File,
): Promise<Project> {
  const form = new FormData();
  form.append('name', name);
  if (description) form.append('description', description);
  form.append('artifacts_file', file);
  // The axios instance defaults to ``Content-Type: application/json``
  // (see ``api/client.ts``). That sticky header overrides axios's
  // FormData auto-detection — without this explicit override the
  // request goes out as JSON, FastAPI's multipart parser sees no
  // form fields, and the route 422s with "Field required" on every
  // Form parameter. Setting ``multipart/form-data`` here lets axios
  // fill in the proper boundary.
  const { data } = await api.post('/projects/import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return ProjectSchema.parse(data);
}

export async function createSampleProject(
  name: string,
  description: string | null,
): Promise<Project> {
  const { data } = await api.post('/projects/from-sample', {
    name,
    description,
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
