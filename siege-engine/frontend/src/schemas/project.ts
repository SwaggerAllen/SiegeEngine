import { z } from 'zod';

export const ArtifactStatusSchema = z.enum([
  'pending',
  'generating',
  'ai_reviewing',
  'awaiting_review',
  'approved',
  'rejected',
  'failed',
]);

export const ArtifactSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  artifact_type: z.string(),
  status: ArtifactStatusSchema,
  is_stale: z.boolean().optional().default(false),
  component_key: z.string().nullable(),
  version: z.number(),
});

export const ProjectSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  git_repo_path: z.string(),
  remote_url: z.string().nullable().optional(),
  github_repo_slug: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  artifact_count: z.number(),
  pipeline_status: z.string().nullable().optional(),
});

export const ProjectDetailSchema = ProjectSchema.extend({
  artifacts: z.array(ArtifactSummarySchema),
});

export const ArtifactSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  artifact_type: z.string(),
  name: z.string(),
  component_key: z.string().nullable(),
  content: z.string().nullable(),
  summary: z.string().nullable().optional(),
  status: ArtifactStatusSchema,
  is_stale: z.boolean().optional().default(false),
  version: z.number(),
  ai_review_feedback: z.record(z.string(), z.unknown()).nullable(),
  human_review_notes: z.string().nullable(),
  file_path: z.string().nullable(),
  git_commit_sha: z.string().nullish(),
  language: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type Project = z.infer<typeof ProjectSchema>;
export type ProjectDetail = z.infer<typeof ProjectDetailSchema>;
export type ArtifactStatus = z.infer<typeof ArtifactStatusSchema>;
export type ArtifactSummary = z.infer<typeof ArtifactSummarySchema>;
export type Artifact = z.infer<typeof ArtifactSchema>;
