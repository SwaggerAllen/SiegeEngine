import { z } from 'zod';
import api from './client';
import { GenerationStatusSchema, TelemetrySummarySchema } from './expansion';

// Phase 7: fan-in inspection API. Fan-in has no draft lifecycle
// (content is written directly via ``FanInContentUpdated``), so
// the API surface is only three endpoints: GET state, POST
// regenerate, POST cancel.
//
// Scope: a single ``comp_id`` — the owning domain comp whose
// fan-in child we're inspecting. The URL puts the fan-in under
// the comp namespace because the fan-in is conceptually a piece
// of that comp (there's exactly one per fanned-out domain comp).

export const FanInNodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  owner_comp_id: z.string(),
  content: z.string(),
  updated_at: z.string(),
});
export type FanInNode = z.infer<typeof FanInNodeSchema>;

export const FanInResponseSchema = z.object({
  node: FanInNodeSchema,
  generation_status: GenerationStatusSchema,
  last_error: z.string().nullable(),
  latest_telemetry: TelemetrySummarySchema.nullable(),
  generation_started_at: z.string().nullish().transform((v) => v ?? null),
  current_attempt: z.number().int().nullish().transform((v) => v ?? null),
  max_attempts: z.number().int().nullish().transform((v) => v ?? null),
  failed_raw_output: z.string().nullish().transform((v) => v ?? null),
});
export type FanInResponse = z.infer<typeof FanInResponseSchema>;

const RegenerateResponseSchema = z.object({ job_id: z.string() });
const CancelResponseSchema = z.object({ cancelled: z.boolean() });
const ResetResponseSchema = z.object({
  ok: z.boolean(),
  nodes_deleted: z.number().int(),
  drafts_discarded: z.number().int(),
  jobs_cancelled: z.number().int(),
});

export async function getFanIn(
  projectId: string,
  compId: string,
): Promise<FanInResponse> {
  const { data } = await api.get(
    `/projects/${projectId}/components/${compId}/fanin`,
  );
  return FanInResponseSchema.parse(data);
}

export async function regenerateFanIn(
  projectId: string,
  compId: string,
): Promise<{ job_id: string }> {
  const { data } = await api.post(
    `/projects/${projectId}/components/${compId}/fanin/regenerate`,
  );
  return RegenerateResponseSchema.parse(data);
}

export async function cancelFanIn(
  projectId: string,
  compId: string,
): Promise<{ cancelled: boolean }> {
  const { data } = await api.post(
    `/projects/${projectId}/components/${compId}/fanin/cancel`,
  );
  return CancelResponseSchema.parse(data);
}

export async function resetFanIn(
  projectId: string,
  compId: string,
): Promise<{ ok: boolean }> {
  const { data } = await api.post(
    `/projects/${projectId}/components/${compId}/fanin/reset`,
  );
  return ResetResponseSchema.parse(data);
}
