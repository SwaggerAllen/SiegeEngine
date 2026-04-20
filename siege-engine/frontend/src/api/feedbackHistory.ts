import { z } from 'zod';
import api from './client';

/**
 * Phase-11 followup B9 — aggregate feedback history per node.
 *
 * Combines user-authored regeneration feedback (pulled from job
 * payloads on the backend) with AI review text (pulled from
 * draft rows). Rendered in a collapsible panel under every
 * BootstrapDraftPanel + FanInPanel so the user can copy the
 * whole history to hand back to the LLM (or to a human
 * reviewer) to pattern-match what prompts are missing.
 */

export const FeedbackEntrySchema = z.object({
  created_at: z.string(),
  source: z.enum(['user', 'ai_review']),
  text: z.string(),
});
export type FeedbackEntry = z.infer<typeof FeedbackEntrySchema>;

export const FeedbackHistoryResponseSchema = z.object({
  entries: z.array(FeedbackEntrySchema),
});
export type FeedbackHistoryResponse = z.infer<typeof FeedbackHistoryResponseSchema>;

export async function getFeedbackHistory(
  projectId: string,
  nodeId: string,
): Promise<FeedbackHistoryResponse> {
  const { data } = await api.get(
    `/projects/${projectId}/nodes/${nodeId}/feedback-history`,
  );
  return FeedbackHistoryResponseSchema.parse(data);
}
