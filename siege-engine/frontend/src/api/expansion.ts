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

export const ExpansionResponseSchema = z.object({
  node: ExpansionNodeSchema,
  pending_draft: ExpansionDraftSchema.nullable(),
  generation_status: GenerationStatusSchema,
  last_error: z.string().nullable(),
});
export type ExpansionResponse = z.infer<typeof ExpansionResponseSchema>;

const FeedbackResponseSchema = z.object({ job_id: z.string() });
const ApproveResponseSchema = z.object({ node: ExpansionNodeSchema });
const DiscardResponseSchema = z.object({ ok: z.boolean() });

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
