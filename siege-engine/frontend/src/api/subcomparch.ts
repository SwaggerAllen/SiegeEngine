import { z } from 'zod';
import api from './client';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

// Per-subcomponent scoping: every request takes
// projectId + parentCompId + subId. Parallel to api/comparch.ts
// with the Phase 5 subcomparch routes nested one level deeper.

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
});
export type SubcomparchResponse = z.infer<typeof SubcomparchResponseSchema>;

const FeedbackResponseSchema = z.object({ job_id: z.string() });
const ApproveResponseSchema = z.object({ node: SubcomparchNodeSchema });
const DiscardResponseSchema = z.object({ ok: z.boolean() });

function _base(projectId: string, parentCompId: string, subId: string): string {
  return (
    `/projects/${projectId}/components/${parentCompId}` +
    `/subcomponents/${subId}/subcomparch`
  );
}

export async function getSubcomparch(
  projectId: string,
  parentCompId: string,
  subId: string
): Promise<SubcomparchResponse> {
  const { data } = await api.get(_base(projectId, parentCompId, subId));
  return SubcomparchResponseSchema.parse(data);
}

export async function postFeedback(
  projectId: string,
  parentCompId: string,
  subId: string,
  feedback: string
): Promise<{ job_id: string }> {
  const { data } = await api.post(
    `${_base(projectId, parentCompId, subId)}/feedback`,
    { feedback }
  );
  return FeedbackResponseSchema.parse(data);
}

export async function approveDraft(
  projectId: string,
  parentCompId: string,
  subId: string,
  draftId: string
): Promise<SubcomparchNode> {
  const { data } = await api.post(
    `${_base(projectId, parentCompId, subId)}/approve`,
    { draft_id: draftId }
  );
  return ApproveResponseSchema.parse(data).node;
}

export async function discardDraft(
  projectId: string,
  parentCompId: string,
  subId: string,
  draftId: string
): Promise<void> {
  const { data } = await api.post(
    `${_base(projectId, parentCompId, subId)}/discard`,
    { draft_id: draftId }
  );
  DiscardResponseSchema.parse(data);
}
