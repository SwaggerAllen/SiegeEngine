import { subreqsApi } from './bootstrapApi';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

export type {
  BootstrapResponse as SubreqsResponse,
  BootstrapNode as SubreqsNode,
  BootstrapDraft as SubreqsDraft,
} from './bootstrapApi';

export { GenerationStatusSchema, TelemetrySummarySchema };

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
