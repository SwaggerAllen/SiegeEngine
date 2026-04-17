import { z } from 'zod';
import api from './client';

// Single query that drives the workspace sidebar tree.
// One request returns every node the tree needs plus status flags
// for each (has_pending_draft, generation_running). Frontend
// assembles the hierarchy from parent_id.

export const NavTreeNodeSchema = z.object({
  id: z.string(),
  tier: z.string(),
  kind: z.string(),
  parent_id: z.string().nullable(),
  name: z.string(),
  display_order: z.number().int(),
  has_content: z.boolean(),
  has_pending_draft: z.boolean(),
  generation_running: z.boolean(),
});
export type NavTreeNode = z.infer<typeof NavTreeNodeSchema>;

export const NavTreeResponseSchema = z.object({
  nodes: z.array(NavTreeNodeSchema),
});
export type NavTreeResponse = z.infer<typeof NavTreeResponseSchema>;

export async function getNavTree(projectId: string): Promise<NavTreeResponse> {
  const { data } = await api.get(`/projects/${projectId}/nav-tree`);
  return NavTreeResponseSchema.parse(data);
}
