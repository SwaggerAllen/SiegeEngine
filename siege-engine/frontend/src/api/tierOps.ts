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
  // Scopes the Review All / Review summary buttons can act on:
  // pending drafts count as reviewable even before approval, since
  // the AI review pass runs against the draft body.
  reviewable_count: z.number(),
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
  jobs_enqueued: z.number(),
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

// ── Review summary (read-only dashboard) ───────────────────────────

const ReviewEntrySchema = z.object({
  scope_id: z.string(),
  scope_label: z.string(),
  score: z.number().int(),
  intro: z.string(),
  handles_count: z.number().int(),
  arch_count: z.number().int(),
  approved_at: z.string().nullable(),
});
export type ReviewEntry = z.infer<typeof ReviewEntrySchema>;

const ReviewMissingSchema = z.object({
  scope_id: z.string(),
  scope_label: z.string(),
  reason: z.string(),
});
export type ReviewMissing = z.infer<typeof ReviewMissingSchema>;

const ScoreStatsSchema = z.object({
  min: z.number().int(),
  max: z.number().int(),
  mean: z.number(),
  median: z.number(),
});
export type ScoreStats = z.infer<typeof ScoreStatsSchema>;

const ScoreBucketsSchema = z.object({
  band_0_30: z.number().int(),
  band_31_60: z.number().int(),
  band_61_85: z.number().int(),
  band_86_100: z.number().int(),
});
export type ScoreBuckets = z.infer<typeof ScoreBucketsSchema>;

export const TierReviewSummarySchema = z.object({
  tier: z.string(),
  tier_name: z.string(),
  draft_count: z.number().int(),
  reviewed_count: z.number().int(),
  missing_count: z.number().int(),
  score_stats: ScoreStatsSchema.nullable(),
  score_buckets: ScoreBucketsSchema,
  handles_count_mean: z.number().nullable(),
  arch_count_mean: z.number().nullable(),
  reviews: z.array(ReviewEntrySchema),
  missing: z.array(ReviewMissingSchema),
});
export type TierReviewSummary = z.infer<typeof TierReviewSummarySchema>;

export async function getTierReviewSummary(
  projectId: string,
  tier: TierName,
): Promise<TierReviewSummary> {
  const r = await api.get(`/projects/${projectId}/tiers/${tier}/review-summary`);
  return TierReviewSummarySchema.parse(r.data);
}
