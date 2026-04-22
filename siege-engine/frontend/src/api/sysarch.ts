import { sysarchApi } from './bootstrapApi';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

export type {
  BootstrapResponse as SysarchResponse,
  BootstrapNode as SysarchNode,
  BootstrapDraft as SysarchDraft,
  ResetResult,
  PromptPreview,
} from './bootstrapApi';

export { GenerationStatusSchema, TelemetrySummarySchema };

// ── Bootstrap CRUD (delegated to shared API) ───────────────────────

export const getSysarch = (projectId: string) => sysarchApi.getState(projectId);

export const postFeedback = (
  projectId: string,
  feedback: string,
  autoRevisionsRequested?: number,
) =>
  autoRevisionsRequested && autoRevisionsRequested > 0
    ? sysarchApi.postFeedback(projectId, feedback, autoRevisionsRequested)
    : sysarchApi.postFeedback(projectId, feedback);

export const approveDraft = (projectId: string, draftId: string) =>
  sysarchApi.approveDraft(projectId, draftId);

export const discardDraft = (projectId: string, draftId: string) =>
  sysarchApi.discardDraft(projectId, draftId);

export const cancelGeneration = (projectId: string) =>
  sysarchApi.cancelGeneration(projectId);

export const resetSysarch = (projectId: string) => sysarchApi.resetTier(projectId);

export const retryReview = (projectId: string) =>
  sysarchApi.retryReview(projectId);

export const getPromptPreview = (projectId: string, feedback: string) =>
  sysarchApi.getPromptPreview(projectId, feedback);
