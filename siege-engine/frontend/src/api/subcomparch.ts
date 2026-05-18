// FUTURE: MCP server endpoint
// /api/projects/:id/refs/:ref/comparch/:comp_id/subs/:sub_id ;
// see docs/migration/mcp-surface.md
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
  change_summary: z.string().nullable().optional(),
});
export type SubcomparchDraft = z.infer<typeof SubcomparchDraftSchema>;

export const SubcomparchResponseSchema = z.object({
  node: SubcomparchNodeSchema,
  pending_draft: SubcomparchDraftSchema.nullable(),
  // Phase 12 — regen-time diff "before" content; see bootstrapApi
  // ResponseSchema for the full story on why this exists and when
  // it's null.
  previous_draft_content: z.string().nullish().transform((v) => v ?? null),
  auto_revision_intermediates: z
    .array(
      z.object({
        label: z.string(),
        content: z.string(),
        auto_revision_pass: z.number().int(),
      }),
    )
    .default([]),
  generation_status: GenerationStatusSchema,
  last_error: z.string().nullable(),
  latest_telemetry: TelemetrySummarySchema.nullable(),
  generation_started_at: z.string().nullish().transform((v) => v ?? null),
  current_attempt: z.number().int().nullish().transform((v) => v ?? null),
  max_attempts: z.number().int().nullish().transform((v) => v ?? null),
  failed_raw_output: z.string().nullish().transform((v) => v ?? null),
  review_text: z.string().default(""),
  review_status: GenerationStatusSchema.default("idle"),
  review_last_error: z.string().nullish().transform((v) => v ?? null),
  review_started_at: z.string().nullish().transform((v) => v ?? null),
  review_current_attempt: z.number().int().nullish().transform((v) => v ?? null),
  review_max_attempts: z.number().int().nullish().transform((v) => v ?? null),
  last_generation_job: z
    .object({
      status: z.string(),
      created_at: z.string(),
      completed_at: z.string().nullable(),
      error_message: z.string().nullable(),
    })
    .nullable()
    .default(null),
  last_content_updated_at: z
    .string()
    .nullish()
    .transform((v) => v ?? null),
});
export type SubcomparchResponse = z.infer<typeof SubcomparchResponseSchema>;

// ── Bootstrap CRUD (delegated to shared API) ───────────────────────

export const getSubcomparch = (
  projectId: string, parentCompId: string, subId: string,
) => subcomparchApi.getState(projectId, parentCompId, subId);

export const postFeedback = (
  projectId: string,
  parentCompId: string,
  subId: string,
  feedback: string,
  autoRevisionsRequested?: number,
) =>
  autoRevisionsRequested && autoRevisionsRequested > 0
    ? subcomparchApi.postFeedback(
        projectId,
        parentCompId,
        subId,
        feedback,
        autoRevisionsRequested,
      )
    : subcomparchApi.postFeedback(projectId, parentCompId, subId, feedback);

export const approveDraft = (
  projectId: string, parentCompId: string, subId: string, draftId: string,
) => subcomparchApi.approveDraft(projectId, parentCompId, subId, draftId);

export const discardDraft = (
  projectId: string, parentCompId: string, subId: string, draftId: string,
) => subcomparchApi.discardDraft(projectId, parentCompId, subId, draftId);

export const cancelGeneration = (
  projectId: string, parentCompId: string, subId: string,
) => subcomparchApi.cancelGeneration(projectId, parentCompId, subId);

export const resetSubcomparch = (
  projectId: string, parentCompId: string, subId: string,
) => subcomparchApi.resetTier(projectId, parentCompId, subId);

export const retryReview = (
  projectId: string, parentCompId: string, subId: string,
) => subcomparchApi.retryReview(projectId, parentCompId, subId);
