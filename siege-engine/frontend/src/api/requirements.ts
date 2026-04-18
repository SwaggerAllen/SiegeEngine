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

export const retryReview = (projectId: string) =>
  requirementsApi.retryReview(projectId);

export const getPromptPreview = (projectId: string, feedback: string) =>
  requirementsApi.getPromptPreview(projectId, feedback);
