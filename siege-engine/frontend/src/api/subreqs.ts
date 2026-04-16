import { z } from 'zod';
import api from './client';
import { subreqsApi } from './bootstrapApi';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

export type {
  BootstrapResponse as SubreqsResponse,
  BootstrapNode as SubreqsNode,
  BootstrapDraft as SubreqsDraft,
} from './bootstrapApi';

export { GenerationStatusSchema, TelemetrySummarySchema };

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

// ── Bootstrap CRUD (delegated to shared API) ───────────────────────

export const getSubreqs = (projectId: string, componentId: string) =>
  subreqsApi.getState(projectId, componentId);

export const postFeedback = (projectId: string, componentId: string, feedback: string) =>
  subreqsApi.postFeedback(projectId, componentId, feedback);

export const approveDraft = (projectId: string, componentId: string, draftId: string) =>
  subreqsApi.approveDraft(projectId, componentId, draftId);

export const discardDraft = (projectId: string, componentId: string, draftId: string) =>
  subreqsApi.discardDraft(projectId, componentId, draftId);

export const cancelGeneration = (projectId: string, componentId: string) =>
  subreqsApi.cancelGeneration(projectId, componentId);

// ── Tier-specific list endpoint ────────────────────────────────────

export async function getSubresponsibilities(
  projectId: string,
  componentId: string
): Promise<SubresponsibilityListResponse> {
  const { data } = await api.get(
    `/projects/${projectId}/components/${componentId}/subresponsibilities`
  );
  return SubresponsibilityListResponseSchema.parse(data);
}
