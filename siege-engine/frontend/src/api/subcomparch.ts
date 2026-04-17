import { z } from 'zod';
import { subcomparchApi } from './bootstrapApi';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

export { GenerationStatusSchema, TelemetrySummarySchema };

export const SubcomparchNodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  parent_id: z.string(),
  content: z.string(),
  updated_at: z.string(),
});
export type SubcomparchNode = z.infer<typeof SubcomparchNodeSchema>;

export const SubcomparchDraftSchema = z.object({
  id: z.string(),
  content: z.string(),
  created_at: z.string(),
});
export type SubcomparchDraft = z.infer<typeof SubcomparchDraftSchema>;

export const SubcomparchResponseSchema = z.object({
  node: SubcomparchNodeSchema,
  pending_draft: SubcomparchDraftSchema.nullable(),
  generation_status: GenerationStatusSchema,
  last_error: z.string().nullable(),
  latest_telemetry: TelemetrySummarySchema.nullable(),
  generation_started_at: z.string().nullish().transform((v) => v ?? null),
  current_attempt: z.number().int().nullish().transform((v) => v ?? null),
  max_attempts: z.number().int().nullish().transform((v) => v ?? null),
});
export type SubcomparchResponse = z.infer<typeof SubcomparchResponseSchema>;

// ── Bootstrap CRUD (delegated to shared API) ───────────────────────

export const getSubcomparch = (
  projectId: string, parentCompId: string, subId: string,
) => subcomparchApi.getState(projectId, parentCompId, subId);

export const postFeedback = (
  projectId: string, parentCompId: string, subId: string, feedback: string,
) => subcomparchApi.postFeedback(projectId, parentCompId, subId, feedback);

export const approveDraft = (
  projectId: string, parentCompId: string, subId: string, draftId: string,
) => subcomparchApi.approveDraft(projectId, parentCompId, subId, draftId);

export const discardDraft = (
  projectId: string, parentCompId: string, subId: string, draftId: string,
) => subcomparchApi.discardDraft(projectId, parentCompId, subId, draftId);

export const cancelGeneration = (
  projectId: string, parentCompId: string, subId: string,
) => subcomparchApi.cancelGeneration(projectId, parentCompId, subId);
