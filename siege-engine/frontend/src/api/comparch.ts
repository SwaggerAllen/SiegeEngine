import { z } from 'zod';
import api from './client';
import { comparchApi } from './bootstrapApi';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

export type {
  BootstrapResponse as ComparchResponse,
  BootstrapNode as ComparchNode,
  BootstrapDraft as ComparchDraft,
} from './bootstrapApi';

export { GenerationStatusSchema, TelemetrySummarySchema };

// ── Subcomponent list ─────────────────────────────────────────────

export const SubcomponentSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  parent_id: z.string(),
  display_order: z.number().int(),
  updated_at: z.string(),
});
export type SubcomponentSummary = z.infer<typeof SubcomponentSummarySchema>;

export const SubcomponentListResponseSchema = z.object({
  subcomponents: z.array(SubcomponentSummarySchema),
});
export type SubcomponentListResponse = z.infer<typeof SubcomponentListResponseSchema>;

// ── Component-local policies list ─────────────────────────────────

export const ComponentLocalPolicySummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  display_order: z.number().int(),
  updated_at: z.string(),
});
export type ComponentLocalPolicySummary = z.infer<
  typeof ComponentLocalPolicySummarySchema
>;

export const ComponentLocalPolicyListResponseSchema = z.object({
  policies: z.array(ComponentLocalPolicySummarySchema),
});
export type ComponentLocalPolicyListResponse = z.infer<
  typeof ComponentLocalPolicyListResponseSchema
>;

// ── Applied policies list ─────────────────────────────────────────

export const AppliedPolicySummarySchema = z.object({
  policy_id: z.string(),
  policy_name: z.string(),
  policy_content: z.string(),
  target_id: z.string(),
});
export type AppliedPolicySummary = z.infer<typeof AppliedPolicySummarySchema>;

export const AppliedPolicyListResponseSchema = z.object({
  applied_policies: z.array(AppliedPolicySummarySchema),
});
export type AppliedPolicyListResponse = z.infer<
  typeof AppliedPolicyListResponseSchema
>;

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

// ── Tier-specific list endpoints ───────────────────────────────────

export async function getSubcomponents(
  projectId: string,
  componentId: string
): Promise<SubcomponentListResponse> {
  const { data } = await api.get(
    `/projects/${projectId}/components/${componentId}/subcomponents`
  );
  return SubcomponentListResponseSchema.parse(data);
}

export async function getComponentLocalPolicies(
  projectId: string,
  componentId: string
): Promise<ComponentLocalPolicyListResponse> {
  const { data } = await api.get(
    `/projects/${projectId}/components/${componentId}/local-policies`
  );
  return ComponentLocalPolicyListResponseSchema.parse(data);
}

export async function getAppliedPolicies(
  projectId: string,
  componentId: string
): Promise<AppliedPolicyListResponse> {
  const { data } = await api.get(
    `/projects/${projectId}/components/${componentId}/applied-policies`
  );
  return AppliedPolicyListResponseSchema.parse(data);
}
