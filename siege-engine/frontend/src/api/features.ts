import { z } from 'zod';
import api from './client';

export const FeatureSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  display_order: z.number().int(),
  group_label: z.string().nullable(),
  is_implicit: z.boolean(),
  updated_at: z.string(),
});
export type FeatureSummary = z.infer<typeof FeatureSummarySchema>;

export const FeatureListResponseSchema = z.object({
  features: z.array(FeatureSummarySchema),
});
export type FeatureListResponse = z.infer<typeof FeatureListResponseSchema>;

export async function getFeatures(projectId: string): Promise<FeatureListResponse> {
  const { data } = await api.get(`/projects/${projectId}/features`);
  return FeatureListResponseSchema.parse(data);
}
