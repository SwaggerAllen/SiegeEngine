import { z } from 'zod';
import api from './client';
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

// ── Components list ────────────────────────────────────────────────

export const ComponentSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.string(),
  display_order: z.number().int(),
  updated_at: z.string(),
  pending_draft_kind: z.string().nullable().optional(),
});
export type ComponentSummary = z.infer<typeof ComponentSummarySchema>;

export const ComponentListResponseSchema = z.object({
  components: z.array(ComponentSummarySchema),
});
export type ComponentListResponse = z.infer<typeof ComponentListResponseSchema>;

// ── Policies list ──────────────────────────────────────────────────

export const PolicySummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  display_order: z.number().int(),
  updated_at: z.string(),
});
export type PolicySummary = z.infer<typeof PolicySummarySchema>;

export const PolicyListResponseSchema = z.object({
  policies: z.array(PolicySummarySchema),
});
export type PolicyListResponse = z.infer<typeof PolicyListResponseSchema>;

// ── Bootstrap CRUD (delegated to shared API) ───────────────────────

export const getSysarch = (projectId: string) =>
  sysarchApi.getState(projectId);

export const postFeedback = (projectId: string, feedback: string) =>
  sysarchApi.postFeedback(projectId, feedback);

export const approveDraft = (projectId: string, draftId: string) =>
  sysarchApi.approveDraft(projectId, draftId);

export const discardDraft = (projectId: string, draftId: string) =>
  sysarchApi.discardDraft(projectId, draftId);

export const cancelGeneration = (projectId: string) =>
  sysarchApi.cancelGeneration(projectId);

export const resetSysarch = (projectId: string) =>
  sysarchApi.resetTier(projectId);

export const getPromptPreview = (projectId: string, feedback: string) =>
  sysarchApi.getPromptPreview(projectId, feedback);

// ── Tier-specific list endpoints ───────────────────────────────────

export async function getComponents(projectId: string): Promise<ComponentListResponse> {
  const { data } = await api.get(`/projects/${projectId}/components`);
  return ComponentListResponseSchema.parse(data);
}

export async function getPolicies(projectId: string): Promise<PolicyListResponse> {
  const { data } = await api.get(`/projects/${projectId}/policies`);
  return PolicyListResponseSchema.parse(data);
}
