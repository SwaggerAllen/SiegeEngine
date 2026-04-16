import { z } from 'zod';
import api from './client';

// Mirror of backend/projects/settings.py ProjectSettings. Keep the
// bounds aligned with the backend pydantic Field constraints so the
// frontend validates client-side before the round trip.
export const ProjectSettingsSchema = z.object({
  generation_timeout_seconds: z.number().int().min(60).max(3600),
});
export type ProjectSettings = z.infer<typeof ProjectSettingsSchema>;

export async function getProjectSettings(projectId: string): Promise<ProjectSettings> {
  const { data } = await api.get(`/projects/${projectId}/settings`);
  return ProjectSettingsSchema.parse(data);
}

export async function updateProjectSettings(
  projectId: string,
  settings: ProjectSettings
): Promise<ProjectSettings> {
  const { data } = await api.put(`/projects/${projectId}/settings`, settings);
  return ProjectSettingsSchema.parse(data);
}
