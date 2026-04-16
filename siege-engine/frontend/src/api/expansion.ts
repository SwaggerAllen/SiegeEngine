import { z } from 'zod';
import api from './client';

export const GenerationStatusSchema = z.enum(['idle', 'running', 'failed']);
export type GenerationStatus = z.infer<typeof GenerationStatusSchema>;

export const ExpansionNodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  updated_at: z.string(),
});
export type ExpansionNode = z.infer<typeof ExpansionNodeSchema>;

export const ExpansionDraftSchema = z.object({
  id: z.string(),
  content: z.string(),
  created_at: z.string(),
});
export type ExpansionDraft = z.infer<typeof ExpansionDraftSchema>;

export const TelemetrySummarySchema = z.object({
  prompt_tokens: z.number().int(),
  completion_tokens: z.number().int(),
  model: z.string(),
  created_at: z.string(),
});
export type TelemetrySummary = z.infer<typeof TelemetrySummarySchema>;

export const ExpansionResponseSchema = z.object({
  node: ExpansionNodeSchema,
  pending_draft: ExpansionDraftSchema.nullable(),
  generation_status: GenerationStatusSchema,
  last_error: z.string().nullable(),
  latest_telemetry: TelemetrySummarySchema.nullable(),
  // ISO-8601 UTC timestamp when the running job was enqueued, or
  // null when no generation is in flight. Server default is null,
  // so nullish() here accepts both null and a missing field for
  // forward-compatibility with older backends.
  generation_started_at: z.string().nullish().transform((v) => v ?? null),
});
export type ExpansionResponse = z.infer<typeof ExpansionResponseSchema>;

const FeedbackResponseSchema = z.object({ job_id: z.string() });
const ApproveResponseSchema = z.object({ node: ExpansionNodeSchema });
const DiscardResponseSchema = z.object({ ok: z.boolean() });
const CancelResponseSchema = z.object({ cancelled: z.boolean() });

export async function getExpansion(projectId: string): Promise<ExpansionResponse> {
  const { data } = await api.get(`/projects/${projectId}/expansion`);
  return ExpansionResponseSchema.parse(data);
}

export async function postFeedback(
  projectId: string,
  feedback: string
): Promise<{ job_id: string }> {
  const { data } = await api.post(`/projects/${projectId}/expansion/feedback`, {
    feedback,
  });
  return FeedbackResponseSchema.parse(data);
}

export async function approveDraft(
  projectId: string,
  draftId: string
): Promise<ExpansionNode> {
  const { data } = await api.post(`/projects/${projectId}/expansion/approve`, {
    draft_id: draftId,
  });
  return ApproveResponseSchema.parse(data).node;
}

export async function discardDraft(
  projectId: string,
  draftId: string
): Promise<void> {
  const { data } = await api.post(`/projects/${projectId}/expansion/discard`, {
    draft_id: draftId,
  });
  DiscardResponseSchema.parse(data);
}

export async function cancelGeneration(projectId: string): Promise<boolean> {
  const { data } = await api.post(`/projects/${projectId}/expansion/cancel`);
  return CancelResponseSchema.parse(data).cancelled;
}
