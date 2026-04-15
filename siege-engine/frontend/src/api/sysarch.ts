import { z } from 'zod';
import api from './client';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

// Parallel to api/requirements.ts. The sysarch node has the same
// four-state panel shape as every other bootstrap doc; the mint
// step produces components + policies that surface via their own
// list endpoints.

export const SysarchNodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  updated_at: z.string(),
});
export type SysarchNode = z.infer<typeof SysarchNodeSchema>;

export const SysarchDraftSchema = z.object({
  id: z.string(),
  content: z.string(),
  created_at: z.string(),
});
export type SysarchDraft = z.infer<typeof SysarchDraftSchema>;

export const SysarchResponseSchema = z.object({
  node: SysarchNodeSchema,
  pending_draft: SysarchDraftSchema.nullable(),
  generation_status: GenerationStatusSchema,
  last_error: z.string().nullable(),
  latest_telemetry: TelemetrySummarySchema.nullable(),
  generation_started_at: z.string().nullish().transform((v) => v ?? null),
});
export type SysarchResponse = z.infer<typeof SysarchResponseSchema>;

const FeedbackResponseSchema = z.object({ job_id: z.string() });
const ApproveResponseSchema = z.object({ node: SysarchNodeSchema });
const DiscardResponseSchema = z.object({ ok: z.boolean() });
const CancelResponseSchema = z.object({ cancelled: z.boolean() });

// ── Components list ────────────────────────────────────────────────

export const ComponentSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.string(),
  display_order: z.number().int(),
  updated_at: z.string(),
  // Phase 6 waiting-on-approval indicator. Non-null when this
  // comp has a pending draft the user still has to approve;
  // ``"subreqs"`` / ``"comparch"`` / ``"subcomparch"``.
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

// ── Request functions ──────────────────────────────────────────────

export async function getSysarch(projectId: string): Promise<SysarchResponse> {
  const { data } = await api.get(`/projects/${projectId}/sysarch`);
  return SysarchResponseSchema.parse(data);
}

export async function postFeedback(
  projectId: string,
  feedback: string
): Promise<{ job_id: string }> {
  const { data } = await api.post(`/projects/${projectId}/sysarch/feedback`, {
    feedback,
  });
  return FeedbackResponseSchema.parse(data);
}

export async function approveDraft(
  projectId: string,
  draftId: string
): Promise<SysarchNode> {
  const { data } = await api.post(`/projects/${projectId}/sysarch/approve`, {
    draft_id: draftId,
  });
  return ApproveResponseSchema.parse(data).node;
}

export async function discardDraft(
  projectId: string,
  draftId: string
): Promise<void> {
  const { data } = await api.post(`/projects/${projectId}/sysarch/discard`, {
    draft_id: draftId,
  });
  DiscardResponseSchema.parse(data);
}

export async function cancelGeneration(projectId: string): Promise<boolean> {
  const { data } = await api.post(`/projects/${projectId}/sysarch/cancel`);
  return CancelResponseSchema.parse(data).cancelled;
}

export async function getComponents(projectId: string): Promise<ComponentListResponse> {
  const { data } = await api.get(`/projects/${projectId}/components`);
  return ComponentListResponseSchema.parse(data);
}

export async function getPolicies(projectId: string): Promise<PolicyListResponse> {
  const { data } = await api.get(`/projects/${projectId}/policies`);
  return PolicyListResponseSchema.parse(data);
}
