import { z } from 'zod';
import api from './client';

// What the subreqs view needs: the top-level resps this component
// was asked to own (Received) + the subresps it broke those into
// (Computed). One endpoint, two lists.

export const ResponsibilitySummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  display_order: z.number().int(),
  updated_at: z.string(),
});
export type ResponsibilitySummary = z.infer<typeof ResponsibilitySummarySchema>;

export const ResponsibilityCoverageSchema = z.object({
  received: z.array(ResponsibilitySummarySchema),
  computed: z.array(ResponsibilitySummarySchema),
});
export type ResponsibilityCoverage = z.infer<typeof ResponsibilityCoverageSchema>;

export async function getResponsibilityCoverage(
  projectId: string,
  compId: string,
): Promise<ResponsibilityCoverage> {
  const { data } = await api.get(
    `/projects/${projectId}/components/${compId}/responsibility-coverage`,
  );
  return ResponsibilityCoverageSchema.parse(data);
}
