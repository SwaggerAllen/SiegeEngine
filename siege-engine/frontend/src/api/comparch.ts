import { comparchApi } from './bootstrapApi';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

export type {
  BootstrapResponse as ComparchResponse,
  BootstrapNode as ComparchNode,
  BootstrapDraft as ComparchDraft,
} from './bootstrapApi';

export { GenerationStatusSchema, TelemetrySummarySchema };

// ── Bootstrap CRUD (delegated to shared API) ───────────────────────

export const getComparch = (projectId: string, componentId: string) =>
  comparchApi.getState(projectId, componentId);

export const postFeedback = (projectId: string, componentId: string, feedback: string) =>
  comparchApi.postFeedback(projectId, componentId, feedback);

export const approveDraft = (projectId: string, componentId: string, draftId: string) =>
  comparchApi.approveDraft(projectId, componentId, draftId);

export const discardDraft = (projectId: string, componentId: string, draftId: string) =>
  comparchApi.discardDraft(projectId, componentId, draftId);

export const cancelGeneration = (projectId: string, componentId: string) =>
  comparchApi.cancelGeneration(projectId, componentId);
