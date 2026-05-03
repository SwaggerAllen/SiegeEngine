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
  // Mean run-time of completed v2.generate_<tier> jobs for this
  // project, in seconds. Excludes queue wait — only the
  // ``locked_at → completed_at`` window. ``null`` when no
  // completed jobs exist yet.
  avg_generation_seconds: z.number().nullable(),
  generation_sample_size: z.number(),
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

export const ResumeTierResultSchema = z.object({
  ok: z.boolean(),
  tier: z.string(),
  scopes_total: z.number(),
  generations_enqueued: z.number(),
  reviews_enqueued: z.number(),
  jobs_enqueued: z.number(),
  scopes_skipped: z.array(SkipSchema),
});
export type ResumeTierResult = z.infer<typeof ResumeTierResultSchema>;

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

export async function resumeTier(
  projectId: string,
  tier: TierName,
): Promise<ResumeTierResult> {
  const r = await api.post(`/projects/${projectId}/tiers/${tier}/resume`);
  return ResumeTierResultSchema.parse(r.data);
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
  batchId?: string,
): Promise<TierReviewSummary> {
  const r = await api.get(
    `/projects/${projectId}/tiers/${tier}/review-summary`,
    batchId ? { params: { batch_id: batchId } } : undefined,
  );
  return TierReviewSummarySchema.parse(r.data);
}

// ── Batches ────────────────────────────────────────────────────────

export const BatchSchema = z.object({
  id: z.string(),
  op_type: z.string(),
  tier: z.string().nullable(),
  scope_keys: z.record(z.string(), z.unknown()),
  params: z.record(z.string(), z.unknown()),
  started_at: z.string().nullable(),
  status: z.string(),
});
export type Batch = z.infer<typeof BatchSchema>;

const BatchListSchema = z.object({
  batches: z.array(BatchSchema),
});

export async function listBatches(
  projectId: string,
  options: { tier?: string; limit?: number } = {},
): Promise<Batch[]> {
  const params: Record<string, string | number> = {};
  if (options.tier) params.tier = options.tier;
  if (options.limit) params.limit = options.limit;
  const r = await api.get(`/projects/${projectId}/batches`, { params });
  return BatchListSchema.parse(r.data).batches;
}

export const BatchResumeResultSchema = z.object({
  ok: z.boolean(),
  batch_id: z.string(),
  requeued: z.number().int(),
  skipped: z.number().int(),
  total_in_batch: z.number().int(),
});
export type BatchResumeResult = z.infer<typeof BatchResumeResultSchema>;

export async function resumeBatch(
  projectId: string,
  batchId: string,
): Promise<BatchResumeResult> {
  const r = await api.post(`/projects/${projectId}/batches/${batchId}/resume`);
  return BatchResumeResultSchema.parse(r.data);
}

// ── Structure summary (read-only dashboard) ────────────────────────

// Eight tiers: the six BootstrapTierConfig tiers plus fanin and
// references. Both deliberately don't have Reset / Review-sweep ops
// (see backend tier_ops_routes module docstring) but get the same
// metadata visibility. Stays a separate constant from TIER_NAMES
// so callers asking "which tiers can I reset" get a different
// answer than "which tiers have a structure summary".
export const STRUCTURE_TIER_NAMES = [
  'expansion',
  'requirements',
  'sysarch',
  'comparch',
  'subcomparch',
  'impl',
  'fanin',
  'references',
] as const;
export type StructureTierName = (typeof STRUCTURE_TIER_NAMES)[number];

const StructureNodeRowSchema = z.object({
  id: z.string(),
  name: z.string(),
  // Per-tier metric shape — open-ended dict. The frontend reads
  // keys from the first row to derive the table's columns.
  metrics: z.record(z.string(), z.unknown()),
});
export type StructureNodeRow = z.infer<typeof StructureNodeRowSchema>;

export const TierStructureSummarySchema = z.object({
  tier: z.string(),
  tier_name: z.string(),
  per_node: z.array(StructureNodeRowSchema),
  // Aggregate values vary by tier — counts, ratios, distribution
  // dicts. Render generically.
  aggregate: z.record(z.string(), z.unknown()),
});
export type TierStructureSummary = z.infer<typeof TierStructureSummarySchema>;

export async function getTierStructureSummary(
  projectId: string,
  tier: StructureTierName,
): Promise<TierStructureSummary> {
  const r = await api.get(`/projects/${projectId}/tiers/${tier}/structure-summary`);
  return TierStructureSummarySchema.parse(r.data);
}
