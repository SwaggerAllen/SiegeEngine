import { z } from 'zod';
import api from './client';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

// Per-component scoping: every request takes ``projectId`` + ``componentId``.
// Mirrors api/requirements.ts but for subreqs routes.

export const SubreqsNodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  updated_at: z.string(),
});
export type SubreqsNode = z.infer<typeof SubreqsNodeSchema>;

export const SubreqsDraftSchema = z.object({
  id: z.string(),
  content: z.string(),
  created_at: z.string(),
});
export type SubreqsDraft = z.infer<typeof SubreqsDraftSchema>;

export const SubreqsResponseSchema = z.object({
  node: SubreqsNodeSchema,
  pending_draft: SubreqsDraftSchema.nullable(),
  generation_status: GenerationStatusSchema,
  last_error: z.string().nullable(),
  latest_telemetry: TelemetrySummarySchema.nullable(),
  generation_started_at: z.string().nullish().transform((v) => v ?? null),
});
export type SubreqsResponse = z.infer<typeof SubreqsResponseSchema>;

const FeedbackResponseSchema = z.object({ job_id: z.string() });
const ApproveResponseSchema = z.object({ node: SubreqsNodeSchema });
const DiscardResponseSchema = z.object({ ok: z.boolean() });
const CancelResponseSchema = z.object({ cancelled: z.boolean() });

// ── Subresponsibilities list ──────────────────────────────────────

export const SubresponsibilitySummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  display_order: z.number().int(),
  updated_at: z.string(),
});
export type SubresponsibilitySummary = z.infer<typeof SubresponsibilitySummarySchema>;

export const SubresponsibilityListResponseSchema = z.object({
  subresponsibilities: z.array(SubresponsibilitySummarySchema),
});
export type SubresponsibilityListResponse = z.infer<
  typeof SubresponsibilityListResponseSchema
>;

// ── Request functions ──────────────────────────────────────────────

export async function getSubreqs(
  projectId: string,
  componentId: string
): Promise<SubreqsResponse> {
  const { data } = await api.get(
    `/projects/${projectId}/components/${componentId}/subrequirements`
  );
  return SubreqsResponseSchema.parse(data);
}

export async function postFeedback(
  projectId: string,
  componentId: string,
  feedback: string
): Promise<{ job_id: string }> {
  const { data } = await api.post(
    `/projects/${projectId}/components/${componentId}/subrequirements/feedback`,
    { feedback }
  );
  return FeedbackResponseSchema.parse(data);
}

export async function approveDraft(
  projectId: string,
  componentId: string,
  draftId: string
): Promise<SubreqsNode> {
  const { data } = await api.post(
    `/projects/${projectId}/components/${componentId}/subrequirements/approve`,
    { draft_id: draftId }
  );
  return ApproveResponseSchema.parse(data).node;
}

export async function discardDraft(
  projectId: string,
  componentId: string,
  draftId: string
): Promise<void> {
  const { data } = await api.post(
    `/projects/${projectId}/components/${componentId}/subrequirements/discard`,
    { draft_id: draftId }
  );
  DiscardResponseSchema.parse(data);
}

export async function cancelGeneration(
  projectId: string,
  componentId: string
): Promise<boolean> {
  const { data } = await api.post(
    `/projects/${projectId}/components/${componentId}/subrequirements/cancel`
  );
  return CancelResponseSchema.parse(data).cancelled;
}

export async function getSubresponsibilities(
  projectId: string,
  componentId: string
): Promise<SubresponsibilityListResponse> {
  const { data } = await api.get(
    `/projects/${projectId}/components/${componentId}/subresponsibilities`
  );
  return SubresponsibilityListResponseSchema.parse(data);
}
