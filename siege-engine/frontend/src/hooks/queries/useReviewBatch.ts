import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  acceptReviewNode,
  closeReviewBatch,
  getReviewBatch,
  getReviewBatchNodeDiff,
  listReviewBatchNodes,
  openReviewBatch,
  type NodeDiff,
  type ReviewBatch,
  type StaleNodeItem,
} from '../../api/review';

/**
 * react-query hooks for the Phase 12 batched-review walker.
 *
 * The walker is a short-lived user flow (open → walk → close) so
 * the hooks keep caching aggressive: the batch row + stale-node
 * list are stable for the lifetime of the pinned offset, and the
 * per-node diff is stable per ``(batch_id, node_id)`` pair. No
 * polling — close either via the close mutation or navigate away.
 */

export const reviewKeys = {
  batch: (projectId: string, batchId: string) =>
    ['reviewBatch', projectId, batchId] as const,
  nodes: (projectId: string, batchId: string) =>
    ['reviewBatchNodes', projectId, batchId] as const,
  nodeDiff: (projectId: string, batchId: string, nodeId: string) =>
    ['reviewBatchNodeDiff', projectId, batchId, nodeId] as const,
};

export function useReviewBatch(projectId: string, batchId: string | undefined) {
  return useQuery<ReviewBatch>({
    queryKey: batchId
      ? reviewKeys.batch(projectId, batchId)
      : ['reviewBatch', projectId, '__none__'],
    queryFn: () => getReviewBatch(projectId, batchId as string),
    enabled: Boolean(batchId),
  });
}

export function useReviewBatchNodes(
  projectId: string,
  batchId: string | undefined,
) {
  return useQuery<StaleNodeItem[]>({
    queryKey: batchId
      ? reviewKeys.nodes(projectId, batchId)
      : ['reviewBatchNodes', projectId, '__none__'],
    queryFn: () => listReviewBatchNodes(projectId, batchId as string),
    enabled: Boolean(batchId),
  });
}

export function useReviewBatchNodeDiff(
  projectId: string,
  batchId: string | undefined,
  nodeId: string | undefined,
) {
  return useQuery<NodeDiff>({
    queryKey:
      batchId && nodeId
        ? reviewKeys.nodeDiff(projectId, batchId, nodeId)
        : ['reviewBatchNodeDiff', projectId, '__none__'],
    queryFn: () =>
      getReviewBatchNodeDiff(projectId, batchId as string, nodeId as string),
    enabled: Boolean(batchId && nodeId),
  });
}

export function useOpenReviewBatchMutation(projectId: string) {
  return useMutation({
    mutationFn: () => openReviewBatch(projectId),
  });
}

export function useCloseReviewBatchMutation(
  projectId: string,
  batchId: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => closeReviewBatch(projectId, batchId),
    onSuccess: (batch) => {
      queryClient.setQueryData(reviewKeys.batch(projectId, batchId), batch);
    },
  });
}

export function useAcceptReviewNodeMutation(
  projectId: string,
  batchId: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (nodeId: string) =>
      acceptReviewNode(projectId, batchId, nodeId),
    onSuccess: () => {
      // Refetch the stale-node list so the accepted node drops out
      // of the left rail. The per-node diff payload stays cached —
      // the user can still scroll back through an accepted node
      // for reference.
      queryClient.invalidateQueries({
        queryKey: reviewKeys.nodes(projectId, batchId),
      });
    },
  });
}
