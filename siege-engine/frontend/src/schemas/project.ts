import { z } from 'zod';

export const ProjectSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  git_repo_path: z.string(),
  remote_url: z.string().nullable().optional(),
  github_repo_slug: z.string().nullable().optional(),
  // Backend returns this on every project response (default false).
  // `.optional()` keeps backward-compat with the small number of test
  // fixtures that don't bother setting it.
  auto_push_enabled: z.boolean().optional(),
  // 'remote' for the GitHub-clone create flow, 'upload' for tarball
  // imports. `.optional()` keeps backward-compat with test fixtures
  // and any pre-b25_project_source-migration response shape.
  source: z.enum(['remote', 'upload']).optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const ProjectDetailSchema = ProjectSchema;

export type Project = z.infer<typeof ProjectSchema>;
export type ProjectDetail = z.infer<typeof ProjectDetailSchema>;
