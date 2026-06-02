// Read-only tier-ops API — info, batches, review summary, structure
// summary. The write endpoints (reset-all / review-sweep / resume /
// regen-below-threshold / full-corpus / exploration-sample) were
// retired alongside the v3 authoring skills.
import { z } from 'zod';
import api from './client';

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
  // Scopes the review summary can act on: pending drafts count as
  // reviewable even before approval, since the AI review pass runs
  // against the draft body.
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

export async function getTierInfo(projectId: string, tier: TierName): Promise<TierInfo> {
  const r = await api.get(`/projects/${projectId}/tiers/${tier}/info`);
  return TierInfoSchema.parse(r.data);
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
  band_0_50: z.number().int(),
  band_51_70: z.number().int(),
  band_71_80: z.number().int(),
  band_81_90: z.number().int(),
  band_91_100: z.number().int(),
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
  options: { tier?: string; cohort_id?: string; op_type?: string; limit?: number } = {},
): Promise<Batch[]> {
  const params: Record<string, string | number> = {};
  if (options.tier) params.tier = options.tier;
  if (options.cohort_id) params.cohort_id = options.cohort_id;
  if (options.op_type) params.op_type = options.op_type;
  if (options.limit) params.limit = options.limit;
  const r = await api.get(`/projects/${projectId}/batches`, { params });
  return BatchListSchema.parse(r.data).batches;
}

// ── Structure summary (read-only dashboard) ────────────────────────

// Eight tiers: the six BootstrapTierConfig tiers plus fanin and
// references.
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
