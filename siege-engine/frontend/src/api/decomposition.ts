import { z } from 'zod';
import api from './client';

// Response shape for GET /projects/{id}/decomposition-graph.
// Used by the Phase 4 stage 10 Cytoscape-powered graph view.

export const DecompositionGraphNodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  tier: z.string(),
  kind: z.string(),
  parent_id: z.string().nullable(),
  display_order: z.number().int(),
});
export type DecompositionGraphNode = z.infer<typeof DecompositionGraphNodeSchema>;

export const DecompositionGraphEdgeSchema = z.object({
  id: z.string(),
  edge_type: z.string(),
  source_id: z.string(),
  target_id: z.string(),
});
export type DecompositionGraphEdge = z.infer<typeof DecompositionGraphEdgeSchema>;

export const DecompositionGraphResponseSchema = z.object({
  nodes: z.array(DecompositionGraphNodeSchema),
  edges: z.array(DecompositionGraphEdgeSchema),
});
export type DecompositionGraphResponse = z.infer<
  typeof DecompositionGraphResponseSchema
>;

export async function getDecompositionGraph(
  projectId: string
): Promise<DecompositionGraphResponse> {
  const { data } = await api.get(`/projects/${projectId}/decomposition-graph`);
  return DecompositionGraphResponseSchema.parse(data);
}
