import { expansionApi } from './bootstrapApi';

export {
  GenerationStatusSchema,
  TelemetrySummarySchema,
  type GenerationStatus,
  type TelemetrySummary,
  type BootstrapResponse as ExpansionResponse,
  type BootstrapNode as ExpansionNode,
  type BootstrapDraft as ExpansionDraft,
  type ResetResult,
  type PromptPreview,
} from './bootstrapApi';

export const getExpansion = (projectId: string) =>
  expansionApi.getState(projectId);

export const postFeedback = (projectId: string, feedback: string) =>
  expansionApi.postFeedback(projectId, feedback);

export const approveDraft = (projectId: string, draftId: string) =>
  expansionApi.approveDraft(projectId, draftId);

export const discardDraft = (projectId: string, draftId: string) =>
  expansionApi.discardDraft(projectId, draftId);

export const cancelGeneration = (projectId: string) =>
  expansionApi.cancelGeneration(projectId);

export const resetExpansion = (projectId: string) =>
  expansionApi.resetTier(projectId);

export const getPromptPreview = (projectId: string, feedback: string) =>
  expansionApi.getPromptPreview(projectId, feedback);
