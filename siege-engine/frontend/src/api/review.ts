// FUTURE: MCP server endpoint
// /api/projects/:id/refs/:ref/review-batches/:batch_id (read paths only —
// open / advance / approve / regen are doomed and replaced by CC skills);
// see docs/migration/mcp-surface.md
import { z } from 'zod';
import api from './client';

/**
 * Phase 12 batched-review API.
 *
 * Three endpoints: open a batch, fetch a batch, close a batch;
 * plus two walker queries: list stale nodes for a batch, and fetch
 * the before/after diff bundle for a single node click.
 */

const ReviewBatchSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  pinned_offset: z.number().int(),
  created_at: z.string(),
  closed_at: z.string().nullable(),
});
export type ReviewBatch = z.infer<typeof ReviewBatchSchema>;

const StaleNodeItemSchema = z.object({
  node_id: z.string(),
  tier: z.string(),
  name: z.string(),
  parent_id: z.string().nullable(),
  reasons: z.array(z.string()),
  is_destructive: z.boolean(),
  topological_order: z.number().int(),
});
export type StaleNodeItem = z.infer<typeof StaleNodeItemSchema>;

const StaleNodesListSchema = z.object({
  items: z.array(StaleNodeItemSchema),
});

const DiffSidesSchema = z.object({
  before: z.string().nullable(),
  after: z.string().nullable(),
});

const FragmentDiffSchema = z.object({
  fragment_kind: z.string(),
  before: z.string().nullable(),
  after: z.string().nullable(),
});

const NodeDiffSchema = z.object({
  node_content: DiffSidesSchema,
  fragments: z.array(FragmentDiffSchema),
  latest_change_summary: z
    .string()
    .nullish()
    .transform((v) => v ?? null),
});
export type NodeDiff = z.infer<typeof NodeDiffSchema>;

export async function openReviewBatch(projectId: string): Promise<ReviewBatch> {
  const { data } = await api.post(`/projects/${projectId}/review/batches`);
  return ReviewBatchSchema.parse(data);
}

export async function closeReviewBatch(
  projectId: string,
  batchId: string,
): Promise<ReviewBatch> {
  const { data } = await api.post(
    `/projects/${projectId}/review/batches/${batchId}/close`,
  );
  return ReviewBatchSchema.parse(data);
}

export async function getReviewBatch(
  projectId: string,
  batchId: string,
): Promise<ReviewBatch> {
  const { data } = await api.get(
    `/projects/${projectId}/review/batches/${batchId}`,
  );
  return ReviewBatchSchema.parse(data);
}

export async function listReviewBatchNodes(
  projectId: string,
  batchId: string,
): Promise<StaleNodeItem[]> {
  const { data } = await api.get(
    `/projects/${projectId}/review/batches/${batchId}/nodes`,
  );
  return StaleNodesListSchema.parse(data).items;
}

export async function getReviewBatchNodeDiff(
  projectId: string,
  batchId: string,
  nodeId: string,
): Promise<NodeDiff> {
  const { data } = await api.get(
    `/projects/${projectId}/review/batches/${batchId}/nodes/${nodeId}/diff`,
  );
  return NodeDiffSchema.parse(data);
}

const AcceptReviewResponseSchema = z.object({
  cleared_count: z.number().int(),
  regen_job_ids: z.array(z.string()),
  is_destructive: z.boolean(),
});
export type AcceptReviewResponse = z.infer<typeof AcceptReviewResponseSchema>;

export async function acceptReviewNode(
  projectId: string,
  batchId: string,
  nodeId: string,
): Promise<AcceptReviewResponse> {
  const { data } = await api.post(
    `/projects/${projectId}/review/batches/${batchId}/nodes/${nodeId}/accept`,
  );
  return AcceptReviewResponseSchema.parse(data);
}
