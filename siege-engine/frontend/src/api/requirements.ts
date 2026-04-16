import { z } from 'zod';
import api from './client';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

// Parallel shape to the expansion API (Phase 1): one singleton
// bootstrap node per project, a pending draft if any, a generation
// status derived from the latest pipeline job, optional last_error,
// and a latest_telemetry summary. The schemas diverge from the
// expansion ones only in name so each module can evolve
// independently.

export const ReqsNodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  updated_at: z.string(),
});
export type ReqsNode = z.infer<typeof ReqsNodeSchema>;

export const ReqsDraftSchema = z.object({
  id: z.string(),
  content: z.string(),
  created_at: z.string(),
});
export type ReqsDraft = z.infer<typeof ReqsDraftSchema>;

export const ReqsResponseSchema = z.object({
  node: ReqsNodeSchema,
  pending_draft: ReqsDraftSchema.nullable(),
  generation_status: GenerationStatusSchema,
  last_error: z.string().nullable(),
  latest_telemetry: TelemetrySummarySchema.nullable(),
  generation_started_at: z.string().nullish().transform((v) => v ?? null),
});
export type ReqsResponse = z.infer<typeof ReqsResponseSchema>;

const FeedbackResponseSchema = z.object({ job_id: z.string() });
const ApproveResponseSchema = z.object({ node: ReqsNodeSchema });
const DiscardResponseSchema = z.object({ ok: z.boolean() });
const CancelResponseSchema = z.object({ cancelled: z.boolean() });
const ResetResponseSchema = z.object({
  ok: z.boolean(),
  nodes_deleted: z.number().int(),
  drafts_discarded: z.number().int(),
  jobs_cancelled: z.number().int(),
});
export type ResetResult = z.infer<typeof ResetResponseSchema>;

// ── Responsibilities list (minted resp_* nodes) ────────────────────

export const ResponsibilitySummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  display_order: z.number().int(),
  updated_at: z.string(),
});
export type ResponsibilitySummary = z.infer<typeof ResponsibilitySummarySchema>;

export const ResponsibilityListResponseSchema = z.object({
  responsibilities: z.array(ResponsibilitySummarySchema),
});
export type ResponsibilityListResponse = z.infer<typeof ResponsibilityListResponseSchema>;

// ── Request functions ──────────────────────────────────────────────

export async function getRequirements(projectId: string): Promise<ReqsResponse> {
  const { data } = await api.get(`/projects/${projectId}/requirements`);
  return ReqsResponseSchema.parse(data);
}

export async function postFeedback(
  projectId: string,
  feedback: string
): Promise<{ job_id: string }> {
  const { data } = await api.post(`/projects/${projectId}/requirements/feedback`, {
    feedback,
  });
  return FeedbackResponseSchema.parse(data);
}

export async function approveDraft(
  projectId: string,
  draftId: string
): Promise<ReqsNode> {
  const { data } = await api.post(`/projects/${projectId}/requirements/approve`, {
    draft_id: draftId,
  });
  return ApproveResponseSchema.parse(data).node;
}

export async function discardDraft(
  projectId: string,
  draftId: string
): Promise<void> {
  const { data } = await api.post(`/projects/${projectId}/requirements/discard`, {
    draft_id: draftId,
  });
  DiscardResponseSchema.parse(data);
}

export async function cancelGeneration(projectId: string): Promise<boolean> {
  const { data } = await api.post(`/projects/${projectId}/requirements/cancel`);
  return CancelResponseSchema.parse(data).cancelled;
}

export async function resetRequirements(projectId: string): Promise<ResetResult> {
  const { data } = await api.post(`/projects/${projectId}/requirements/reset`);
  return ResetResponseSchema.parse(data);
}

const PromptPreviewSchema = z.object({
  system_prompt: z.string(),
  user_prompt: z.string(),
});
export type PromptPreview = z.infer<typeof PromptPreviewSchema>;

export async function getPromptPreview(
  projectId: string,
  feedback: string
): Promise<PromptPreview> {
  const { data } = await api.post(`/projects/${projectId}/requirements/prompt-preview`, {
    feedback,
  });
  return PromptPreviewSchema.parse(data);
}

export async function getResponsibilities(
  projectId: string
): Promise<ResponsibilityListResponse> {
  const { data } = await api.get(`/projects/${projectId}/responsibilities`);
  return ResponsibilityListResponseSchema.parse(data);
}
