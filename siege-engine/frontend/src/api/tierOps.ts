import { z } from 'zod';
import api from './client';

/**
 * Tier-ops API — bulk reset and bulk AI-review for an entire tier.
 *
 * Wraps `POST /projects/{project_id}/tiers/{tier}/reset-all`,
 * `POST /projects/{project_id}/tiers/{tier}/review-sweep`, and
 * `GET  /projects/{project_id}/tiers/{tier}/info`.
 */

export const TIER_NAMES = [
  'expansion',
  'requirements',
  'sysarch',
  'subreqs',
  'comparch',
  'subcomparch',
  'impl',
] as const;
export type TierName = (typeof TIER_NAMES)[number];

export const TierInfoSchema = z.object({
  tier: z.string(),
  tier_name: z.string(),
  node_count: z.number(),
  nodes_with_content: z.number(),
  supports_reset: z.boolean(),
  supports_review: z.boolean(),
});
export type TierInfo = z.infer<typeof TierInfoSchema>;

const SkipSchema = z.object({
  scope_ids: z.array(z.string()),
  status: z.number(),
  detail: z.unknown(),
});

export const ResetAllResultSchema = z.object({
  ok: z.boolean(),
  tier: z.string(),
  scopes_total: z.number(),
  scopes_succeeded: z.number(),
  scopes_skipped: z.array(SkipSchema),
  jobs_cancelled: z.number(),
  drafts_discarded: z.number(),
  nodes_deleted: z.number(),
});
export type ResetAllResult = z.infer<typeof ResetAllResultSchema>;

export const ReviewSweepResultSchema = z.object({
  ok: z.boolean(),
  tier: z.string(),
  scopes_total: z.number(),
  jobs_enqueued: z.number(),
  scopes_skipped: z.array(SkipSchema),
});
export type ReviewSweepResult = z.infer<typeof ReviewSweepResultSchema>;

export async function getTierInfo(projectId: string, tier: TierName): Promise<TierInfo> {
  const r = await api.get(`/projects/${projectId}/tiers/${tier}/info`);
  return TierInfoSchema.parse(r.data);
}

export async function resetTier(projectId: string, tier: TierName): Promise<ResetAllResult> {
  const r = await api.post(`/projects/${projectId}/tiers/${tier}/reset-all`);
  return ResetAllResultSchema.parse(r.data);
}

export async function reviewSweepTier(
  projectId: string,
  tier: TierName,
): Promise<ReviewSweepResult> {
  const r = await api.post(`/projects/${projectId}/tiers/${tier}/review-sweep`);
  return ReviewSweepResultSchema.parse(r.data);
}
