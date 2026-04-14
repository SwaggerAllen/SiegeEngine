import { z } from 'zod';
import api from './client';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

// Per-component scoping: every request takes projectId + componentId.
// Parallel to api/subreqs.ts with the Phase 4 comparch routes.

export const ComparchNodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  updated_at: z.string(),
});
export type ComparchNode = z.infer<typeof ComparchNodeSchema>;

export const ComparchDraftSchema = z.object({
  id: z.string(),
  content: z.string(),
  created_at: z.string(),
});
export type ComparchDraft = z.infer<typeof ComparchDraftSchema>;

export const ComparchResponseSchema = z.object({
  node: ComparchNodeSchema,
  pending_draft: ComparchDraftSchema.nullable(),
  generation_status: GenerationStatusSchema,
  last_error: z.string().nullable(),
  latest_telemetry: TelemetrySummarySchema.nullable(),
});
export type ComparchResponse = z.infer<typeof ComparchResponseSchema>;

const FeedbackResponseSchema = z.object({ job_id: z.string() });
const ApproveResponseSchema = z.object({ node: ComparchNodeSchema });
const DiscardResponseSchema = z.object({ ok: z.boolean() });

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

// ── Request functions ─────────────────────────────────────────────

export async function getComparch(
  projectId: string,
  componentId: string
): Promise<ComparchResponse> {
  const { data } = await api.get(
    `/projects/${projectId}/components/${componentId}/comparch`
  );
  return ComparchResponseSchema.parse(data);
}

export async function postFeedback(
  projectId: string,
  componentId: string,
  feedback: string
): Promise<{ job_id: string }> {
  const { data } = await api.post(
    `/projects/${projectId}/components/${componentId}/comparch/feedback`,
    { feedback }
  );
  return FeedbackResponseSchema.parse(data);
}

export async function approveDraft(
  projectId: string,
  componentId: string,
  draftId: string
): Promise<ComparchNode> {
  const { data } = await api.post(
    `/projects/${projectId}/components/${componentId}/comparch/approve`,
    { draft_id: draftId }
  );
  return ApproveResponseSchema.parse(data).node;
}

export async function discardDraft(
  projectId: string,
  componentId: string,
  draftId: string
): Promise<void> {
  const { data } = await api.post(
    `/projects/${projectId}/components/${componentId}/comparch/discard`,
    { draft_id: draftId }
  );
  DiscardResponseSchema.parse(data);
}

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
