import { z } from 'zod';
import { implSubApi, implTopLevelApi } from './bootstrapApi';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

export { GenerationStatusSchema, TelemetrySummarySchema };

// Phase 8: implementation node responses. One scope key:
// `owner_id`, which is the comp/sub that owns the impl. URL
// shape varies by owner (top-level vs sub), but response shape
// is identical — impl's own node id + its parent_id (the owner).

export const ImplNodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  parent_id: z.string(),
  content: z.string(),
  updated_at: z.string(),
});
export type ImplNode = z.infer<typeof ImplNodeSchema>;

export const ImplDraftSchema = z.object({
  id: z.string(),
  content: z.string(),
  created_at: z.string(),
});
export type ImplDraft = z.infer<typeof ImplDraftSchema>;

export const ImplResponseSchema = z.object({
  node: ImplNodeSchema,
  pending_draft: ImplDraftSchema.nullable(),
  generation_status: GenerationStatusSchema,
  last_error: z.string().nullable(),
  latest_telemetry: TelemetrySummarySchema.nullable(),
  generation_started_at: z.string().nullish().transform((v) => v ?? null),
});
export type ImplResponse = z.infer<typeof ImplResponseSchema>;

// ── Top-level (un-fanned-out) impl CRUD ────────────────────────────
// Signature: (projectId, compId) where compId is the top-level
// comp that owns the impl. The generate handler reads the
// comp's comparch content and expects non-empty.

export const getImplTopLevel = (projectId: string, compId: string) =>
  implTopLevelApi.getState(projectId, compId);

export const postImplTopLevelFeedback = (
  projectId: string,
  compId: string,
  feedback: string,
) => implTopLevelApi.postFeedback(projectId, compId, feedback);

export const approveImplTopLevelDraft = (
  projectId: string,
  compId: string,
  draftId: string,
) => implTopLevelApi.approveDraft(projectId, compId, draftId);

export const discardImplTopLevelDraft = (
  projectId: string,
  compId: string,
  draftId: string,
) => implTopLevelApi.discardDraft(projectId, compId, draftId);

export const cancelImplTopLevelGeneration = (projectId: string, compId: string) =>
  implTopLevelApi.cancelGeneration(projectId, compId);

// ── Per-subcomponent impl CRUD ─────────────────────────────────────
// Signature: (projectId, parentCompId, subId). The sub is the
// owner; parentCompId is the URL context so the client has a
// clear navigation trail.

export const getImplSub = (
  projectId: string,
  parentCompId: string,
  subId: string,
) => implSubApi.getState(projectId, parentCompId, subId);

export const postImplSubFeedback = (
  projectId: string,
  parentCompId: string,
  subId: string,
  feedback: string,
) => implSubApi.postFeedback(projectId, parentCompId, subId, feedback);

export const approveImplSubDraft = (
  projectId: string,
  parentCompId: string,
  subId: string,
  draftId: string,
) => implSubApi.approveDraft(projectId, parentCompId, subId, draftId);

export const discardImplSubDraft = (
  projectId: string,
  parentCompId: string,
  subId: string,
  draftId: string,
) => implSubApi.discardDraft(projectId, parentCompId, subId, draftId);

export const cancelImplSubGeneration = (
  projectId: string,
  parentCompId: string,
  subId: string,
) => implSubApi.cancelGeneration(projectId, parentCompId, subId);
