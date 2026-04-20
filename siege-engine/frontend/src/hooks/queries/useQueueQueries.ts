import { useQuery } from '@tanstack/react-query';
import { listQueue, type QueueListResponse } from '../../api/queue';
import { queueKeys } from './useProjectEventStream';

export { queueKeys };

/**
 * Phase 11 — subscribe to a project's pending-change queue.
 *
 * Refetches driven primarily by SSE (``QueueInstructionAppended``,
 * ``QueueInstructionDiscarded``, ``QueueApplying``, ``QueueApplied``,
 * ``QueueFailed``) invalidating ``queueKeys.project(projectId)``.
 * Polls every 2s while any row is ``running`` to keep the apply-
 * progress indicator fresh (Job payload attempt counters aren't
 * event-sourced — mirrors the pattern in ``useBootstrapHooks``).
 */
export function useQueueList(projectId: string, enabled: boolean = true) {
  return useQuery<QueueListResponse>({
    queryKey: queueKeys.project(projectId),
    queryFn: () => listQueue(projectId),
    enabled: enabled && !!projectId,
    refetchInterval: (query) => {
      const data = query.state.data as QueueListResponse | undefined;
      if (!data) return false;
      const hasRunning = data.rows.some((r) => r.status === 'running');
      return hasRunning ? 2000 : false;
    },
  });
}
