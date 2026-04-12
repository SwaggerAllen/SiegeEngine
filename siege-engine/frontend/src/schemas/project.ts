import { z } from 'zod';

export const ProjectSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  git_repo_path: z.string(),
  remote_url: z.string().nullable().optional(),
  github_repo_slug: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const ProjectDetailSchema = ProjectSchema;

export type Project = z.infer<typeof ProjectSchema>;
export type ProjectDetail = z.infer<typeof ProjectDetailSchema>;
