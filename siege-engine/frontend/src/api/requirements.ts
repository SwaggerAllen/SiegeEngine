import { z } from 'zod';
import api from './client';
import { requirementsApi } from './bootstrapApi';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

export type {
  BootstrapResponse as ReqsResponse,
  BootstrapNode as ReqsNode,
  BootstrapDraft as ReqsDraft,
  ResetResult,
  PromptPreview,
} from './bootstrapApi';

// Re-export for backward compat (other API files import these)
export { GenerationStatusSchema, TelemetrySummarySchema };

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

// ── Bootstrap CRUD (delegated to shared API) ───────────────────────

export const getRequirements = (projectId: string) =>
  requirementsApi.getState(projectId);

export const postFeedback = (projectId: string, feedback: string) =>
  requirementsApi.postFeedback(projectId, feedback);

export const approveDraft = (projectId: string, draftId: string) =>
  requirementsApi.approveDraft(projectId, draftId);

export const discardDraft = (projectId: string, draftId: string) =>
  requirementsApi.discardDraft(projectId, draftId);

export const cancelGeneration = (projectId: string) =>
  requirementsApi.cancelGeneration(projectId);

export const resetRequirements = (projectId: string) =>
  requirementsApi.resetTier(projectId);

export const getPromptPreview = (projectId: string, feedback: string) =>
  requirementsApi.getPromptPreview(projectId, feedback);

// ── Tier-specific list endpoint ────────────────────────────────────

export async function getResponsibilities(
  projectId: string
): Promise<ResponsibilityListResponse> {
  const { data } = await api.get(`/projects/${projectId}/responsibilities`);
  return ResponsibilityListResponseSchema.parse(data);
}
