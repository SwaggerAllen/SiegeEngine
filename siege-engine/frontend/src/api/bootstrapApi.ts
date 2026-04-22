import { z } from 'zod';
import api from './client';

export const GenerationStatusSchema = z.enum(['idle', 'running', 'failed']);
export type GenerationStatus = z.infer<typeof GenerationStatusSchema>;

export const TelemetrySummarySchema = z.object({
  prompt_tokens: z.number().int(),
  completion_tokens: z.number().int(),
  model: z.string(),
  created_at: z.string(),
});
export type TelemetrySummary = z.infer<typeof TelemetrySummarySchema>;

const NodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  updated_at: z.string(),
});

const DraftSchema = z.object({
  id: z.string(),
  content: z.string(),
  created_at: z.string(),
});

const ResponseSchema = z.object({
  node: NodeSchema,
  pending_draft: DraftSchema.nullable(),
  // Phase 12 — regen-time diff. Content of the most recently
  // discarded draft for this target, or ``null`` when the target
  // has never had a discarded draft (brand-new bootstrap, or the
  // first regen after approval — in which case the panel falls
  // back to the approved node content as the diff's "before").
  previous_draft_content: z.string().nullish().transform((v) => v ?? null),
  generation_status: GenerationStatusSchema,
  last_error: z.string().nullable(),
  latest_telemetry: TelemetrySummarySchema.nullable(),
  generation_started_at: z.string().nullish().transform((v) => v ?? null),
  current_attempt: z.number().int().nullish().transform((v) => v ?? null),
  max_attempts: z.number().int().nullish().transform((v) => v ?? null),
  failed_raw_output: z.string().nullish().transform((v) => v ?? null),
  // Phase 8 — AI self-review fields. Empty text / "idle" for
  // tiers without a configured review_job_type.
  review_text: z.string().default(""),
  review_status: GenerationStatusSchema.default("idle"),
  review_last_error: z.string().nullish().transform((v) => v ?? null),
  review_started_at: z.string().nullish().transform((v) => v ?? null),
  review_current_attempt: z.number().int().nullish().transform((v) => v ?? null),
  review_max_attempts: z.number().int().nullish().transform((v) => v ?? null),
  // Phase 9 — staleness flags. `is_stale` mirrors whether this
  // tier has any active upstream staleness marker;
  // `staleness_reasons` lists the distinct reason codes so the
  // panel can surface "upstream X changed" context above the
  // draft view.
  is_stale: z.boolean().default(false),
  staleness_reasons: z.array(z.string()).default([]),
});

const FeedbackResponseSchema = z.object({ job_id: z.string() });
const ApproveResponseSchema = z.object({ node: NodeSchema });
const DiscardResponseSchema = z.object({ ok: z.boolean() });
const CancelResponseSchema = z.object({ cancelled: z.boolean() });
const ResetResponseSchema = z.object({
  ok: z.boolean(),
  nodes_deleted: z.number().int(),
  drafts_discarded: z.number().int(),
  jobs_cancelled: z.number().int(),
});
const PromptPreviewSchema = z.object({
  system_prompt: z.string(),
  user_prompt: z.string(),
});

export type BootstrapNode = z.infer<typeof NodeSchema>;
export type BootstrapDraft = z.infer<typeof DraftSchema>;
export type BootstrapResponse = z.infer<typeof ResponseSchema>;
export type ResetResult = z.infer<typeof ResetResponseSchema>;
export type PromptPreview = z.infer<typeof PromptPreviewSchema>;

export interface BootstrapApi {
  getState: (...scopeIds: string[]) => Promise<BootstrapResponse>;
  postFeedback: (...args: [...string[], string]) => Promise<{ job_id: string }>;
  approveDraft: (...args: [...string[], string]) => Promise<BootstrapNode>;
  discardDraft: (...args: [...string[], string]) => Promise<void>;
  cancelGeneration: (...scopeIds: string[]) => Promise<boolean>;
  resetTier: (...scopeIds: string[]) => Promise<ResetResult>;
  retryReview: (...scopeIds: string[]) => Promise<{ job_id: string }>;
  getPromptPreview: (...args: [...string[], string]) => Promise<PromptPreview>;
}

export function makeBootstrapApi(
  buildBase: (...scopeIds: string[]) => string
): BootstrapApi {
  return {
    async getState(...scopeIds: string[]) {
      const { data } = await api.get(buildBase(...scopeIds));
      return ResponseSchema.parse(data);
    },
    async postFeedback(...args: string[]) {
      const feedback = args[args.length - 1];
      const scopeIds = args.slice(0, -1);
      const { data } = await api.post(`${buildBase(...scopeIds)}/feedback`, {
        feedback,
      });
      return FeedbackResponseSchema.parse(data);
    },
    async approveDraft(...args: string[]) {
      const draftId = args[args.length - 1];
      const scopeIds = args.slice(0, -1);
      const { data } = await api.post(`${buildBase(...scopeIds)}/approve`, {
        draft_id: draftId,
      });
      return ApproveResponseSchema.parse(data).node;
    },
    async discardDraft(...args: string[]) {
      const draftId = args[args.length - 1];
      const scopeIds = args.slice(0, -1);
      const { data } = await api.post(`${buildBase(...scopeIds)}/discard`, {
        draft_id: draftId,
      });
      DiscardResponseSchema.parse(data);
    },
    async cancelGeneration(...scopeIds: string[]) {
      const { data } = await api.post(`${buildBase(...scopeIds)}/cancel`);
      return CancelResponseSchema.parse(data).cancelled;
    },
    async resetTier(...scopeIds: string[]) {
      const { data } = await api.post(`${buildBase(...scopeIds)}/reset`);
      return ResetResponseSchema.parse(data);
    },
    async retryReview(...scopeIds: string[]) {
      const { data } = await api.post(`${buildBase(...scopeIds)}/review/retry`);
      return FeedbackResponseSchema.parse(data);
    },
    async getPromptPreview(...args: string[]) {
      const feedback = args[args.length - 1];
      const scopeIds = args.slice(0, -1);
      const { data } = await api.post(
        `${buildBase(...scopeIds)}/prompt-preview`,
        { feedback }
      );
      return PromptPreviewSchema.parse(data);
    },
  };
}

export const expansionApi = makeBootstrapApi(
  (projectId) => `/projects/${projectId}/expansion`
);

export const requirementsApi = makeBootstrapApi(
  (projectId) => `/projects/${projectId}/requirements`
);

export const sysarchApi = makeBootstrapApi(
  (projectId) => `/projects/${projectId}/sysarch`
);

export const subreqsApi = makeBootstrapApi(
  (projectId, componentId) =>
    `/projects/${projectId}/components/${componentId}/subrequirements`
);

export const comparchApi = makeBootstrapApi(
  (projectId, componentId) =>
    `/projects/${projectId}/components/${componentId}/comparch`
);

export const subcomparchApi = makeBootstrapApi(
  (projectId, parentCompId, subId) =>
    `/projects/${projectId}/components/${parentCompId}/subcomponents/${subId}/subcomparch`
);

// Phase 8: impl gets two URL shapes. `implTopLevelApi` is for
// un-fanned-out top-level comps (impl lives directly under the
// comp). `implSubApi` is for per-subcomponent impls.
export const implTopLevelApi = makeBootstrapApi(
  (projectId, compId) => `/projects/${projectId}/components/${compId}/impl`
);

export const implSubApi = makeBootstrapApi(
  (projectId, parentCompId, subId) =>
    `/projects/${projectId}/components/${parentCompId}/subcomponents/${subId}/impl`
);
