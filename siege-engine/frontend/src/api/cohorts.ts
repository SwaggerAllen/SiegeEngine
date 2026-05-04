import { z } from 'zod';
import api from './client';

/**
 * Cohorts + sampler-config API.
 *
 * Cohorts hold saved selections of comp IDs to drive iteration
 * cycles at the next tier down. Sampler configs hold the
 * stratified-sampler axis weights per tier — editable without a
 * deploy so axis tuning doesn't interrupt in-flight generations.
 */

export const CohortSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  tier: z.string(),
  name: z.string(),
  comp_ids: z.array(z.string()),
  version: z.number().int(),
  archived: z.boolean(),
  created_at: z.string().nullable(),
  updated_at: z.string().nullable(),
});
export type Cohort = z.infer<typeof CohortSchema>;

const CohortListSchema = z.object({
  cohorts: z.array(CohortSchema),
});

export async function listCohorts(
  projectId: string,
  options: { tier?: string; archived?: boolean } = {},
): Promise<Cohort[]> {
  const params: Record<string, string | boolean> = {};
  if (options.tier) params.tier = options.tier;
  if (options.archived !== undefined) params.archived = options.archived;
  const r = await api.get(`/projects/${projectId}/cohorts`, { params });
  return CohortListSchema.parse(r.data).cohorts;
}

export async function getCohort(projectId: string, cohortId: string): Promise<Cohort> {
  const r = await api.get(`/projects/${projectId}/cohorts/${cohortId}`);
  return CohortSchema.parse(r.data);
}

export async function createCohort(
  projectId: string,
  body: { tier: string; name: string; comp_ids: string[] },
): Promise<Cohort> {
  const r = await api.post(`/projects/${projectId}/cohorts`, body);
  return CohortSchema.parse(r.data);
}

export async function patchCohort(
  projectId: string,
  cohortId: string,
  body: { name?: string; comp_ids?: string[]; archived?: boolean },
): Promise<Cohort> {
  const r = await api.patch(`/projects/${projectId}/cohorts/${cohortId}`, body);
  return CohortSchema.parse(r.data);
}

export const AutoSuggestResultSchema = z.object({
  tier: z.string(),
  target_size: z.number().int(),
  suggested_ids: z.array(z.string()),
  axes_used: z.array(z.string()),
});
export type AutoSuggestResult = z.infer<typeof AutoSuggestResultSchema>;

export async function autoSuggestCohort(
  projectId: string,
  tier: string,
  body: { target_size: number; exclude_ids?: string[] },
): Promise<AutoSuggestResult> {
  const r = await api.post(
    `/projects/${projectId}/cohorts/auto-suggest`,
    { target_size: body.target_size, exclude_ids: body.exclude_ids ?? [] },
    { params: { tier } },
  );
  return AutoSuggestResultSchema.parse(r.data);
}

// ── Sampler config ────────────────────────────────────────────────

export const SamplerConfigSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  tier: z.string(),
  axes: z.object({ axes: z.array(z.record(z.string(), z.unknown())) }),
  updated_at: z.string().nullable(),
});
export type SamplerConfig = z.infer<typeof SamplerConfigSchema>;

export async function getSamplerConfig(
  projectId: string,
  tier: string,
): Promise<SamplerConfig> {
  const r = await api.get(`/projects/${projectId}/sampler-configs/${tier}`);
  return SamplerConfigSchema.parse(r.data);
}

export async function putSamplerConfig(
  projectId: string,
  tier: string,
  axes: SamplerConfig['axes'],
): Promise<SamplerConfig> {
  const r = await api.put(`/projects/${projectId}/sampler-configs/${tier}`, { axes });
  return SamplerConfigSchema.parse(r.data);
}

// ── Regenerate cohort + exploration / full-corpus ─────────────────

const SkippedScopeSchema = z.object({
  scope_ids: z.array(z.string()),
  status: z.number(),
  detail: z.unknown(),
});

export const RegenerateCohortResultSchema = z.object({
  ok: z.boolean(),
  batch_id: z.string(),
  cohort_id: z.string(),
  mode: z.enum(['fresh', 'review']),
  target_tier: z.string(),
  scopes_total: z.number().int(),
  scopes_succeeded: z.number().int(),
  scopes_skipped: z.array(SkippedScopeSchema),
});
export type RegenerateCohortResult = z.infer<typeof RegenerateCohortResultSchema>;

export async function regenerateCohort(
  projectId: string,
  cohortId: string,
  mode: 'fresh' | 'review',
): Promise<RegenerateCohortResult> {
  const r = await api.post(`/projects/${projectId}/cohorts/${cohortId}/regenerate`, { mode });
  return RegenerateCohortResultSchema.parse(r.data);
}

export const ExplorationSampleResultSchema = z.object({
  ok: z.boolean(),
  batch_id: z.string(),
  picked_comp_ids: z.array(z.string()),
  scopes_total: z.number().int(),
  scopes_succeeded: z.number().int(),
  scopes_skipped: z.array(SkippedScopeSchema),
});
export type ExplorationSampleResult = z.infer<typeof ExplorationSampleResultSchema>;

export async function generateExplorationSample(
  projectId: string,
  body: { count: number; exclude_cohort_id?: string },
): Promise<ExplorationSampleResult> {
  const r = await api.post(
    `/projects/${projectId}/tiers/subcomparch/exploration-sample`,
    body,
  );
  return ExplorationSampleResultSchema.parse(r.data);
}

export const FullCorpusResultSchema = z.object({
  ok: z.boolean(),
  batch_id: z.string(),
  scopes_total: z.number().int(),
  scopes_succeeded: z.number().int(),
  scopes_skipped: z.array(SkippedScopeSchema),
});
export type FullCorpusResult = z.infer<typeof FullCorpusResultSchema>;

export async function generateFullCorpus(
  projectId: string,
): Promise<FullCorpusResult> {
  const r = await api.post(`/projects/${projectId}/tiers/subcomparch/full-corpus`);
  return FullCorpusResultSchema.parse(r.data);
}
