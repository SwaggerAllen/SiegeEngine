import { useQuery } from '@tanstack/react-query';
import {
  getFeedbackHistory,
  type FeedbackHistoryResponse,
} from '../../api/feedbackHistory';

/**
 * Query key factory + React Query hook for the B9 feedback
 * history panel. Invalidated by the SSE stream on any
 * DraftReviewUpdated event or generation job completion
 * affecting this node.
 */
export const feedbackHistoryKeys = {
  all: ['feedbackHistory'] as const,
  node: (projectId: string, nodeId: string) =>
    ['feedbackHistory', projectId, nodeId] as const,
};

export function useFeedbackHistory(
  projectId: string,
  nodeId: string | null | undefined,
) {
  return useQuery<FeedbackHistoryResponse>({
    queryKey: feedbackHistoryKeys.node(projectId, nodeId ?? ''),
    queryFn: () => getFeedbackHistory(projectId, nodeId as string),
    enabled: Boolean(projectId && nodeId),
  });
}
