import { z } from 'zod';
import api from './client';

// Consolidated structure snapshot for the workspace. One fetch
// returns every node + edge + status flag in the project, with
// the event-log offset at the time of read. The offset pairs
// with the SSE /events/stream endpoint's ?since query param so
// no event is lost between snapshot read and stream subscribe.

export const StructureNodeSchema = z.object({
  id: z.string(),
  tier: z.string(),
  kind: z.string(),
  parent_id: z.string().nullable(),
  name: z.string(),
  display_order: z.number().int(),
  // Content is populated for "light" tiers (resp, feat, policy,
  // vocab, ref) whose only UI is a list view — the text appears
  // directly in ResponsibilityCoverage / lists. Heavy tiers
  // (comp, subreqs, impl, fanin, expansion, reqs, sysarch) have
  // dedicated detail endpoints and leave this empty.
  content: z.string(),
  has_content: z.boolean(),
  has_pending_draft: z.boolean(),
  generation_running: z.boolean(),
  // True when the latest generation job targeting this node
  // ended in ``failed``. Surfaced as a red dot in the sidebar
  // tree ahead of amber pending / running badges; cleared when
  // the user enqueues a retry.
  has_error: z.boolean(),
  // True when the latest generation job was cancelled and no
  // replacement is queued. Drives the blue dot in the sidebar
  // tree — signals "idle but explicitly waiting on user retry".
  has_cancelled_latest_job: z.boolean(),
  // Sysarch-time techspec + pubapi fragments for ``comp`` tier
  // nodes — populated when sysarch_mint writes them, empty
  // string otherwise. Drives the component Overview tab so the
  // user can review what sysarch said about this comp before
  // triggering comparch. Empty for non-comp tiers.
  techspec: z.string(),
  pubapi: z.string(),
});
export type StructureNode = z.infer<typeof StructureNodeSchema>;

export const StructureEdgeSchema = z.object({
  id: z.string(),
  edge_type: z.string(),
  source_id: z.string(),
  target_id: z.string(),
});
export type StructureEdge = z.infer<typeof StructureEdgeSchema>;

export const StructureResponseSchema = z.object({
  offset: z.number().int(),
  nodes: z.array(StructureNodeSchema),
  edges: z.array(StructureEdgeSchema),
});
export type StructureResponse = z.infer<typeof StructureResponseSchema>;

export async function getProjectStructure(projectId: string): Promise<StructureResponse> {
  const { data } = await api.get(`/projects/${projectId}/structure`);
  return StructureResponseSchema.parse(data);
}
