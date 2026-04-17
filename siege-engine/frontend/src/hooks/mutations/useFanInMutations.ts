import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as faninApi from '../../api/fanin';
import { faninKeys } from '../queries/useFanInQueries';

/**
 * Phase 7 fan-in mutations. Two ops only — no draft lifecycle:
 *
 * - ``regenerate``: enqueue a fresh ``v2.generate_fanin`` job.
 *   The backend dedups identical payloads, so spamming the
 *   button collapses to a single queued job.
 * - ``cancel``: stop an in-flight regen.
 *
 * Both invalidate the fan-in detail query so the status flips
 * (``idle`` → ``running`` on regen, ``running`` → ``idle`` /
 * ``cancelled`` on cancel) and the polling picks up fresh
 * telemetry once the generation completes.
 */
export function useFanInRegenerateMutation(projectId: string, compId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => faninApi.regenerateFanIn(projectId, compId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: faninKeys.detail(projectId, compId),
      });
    },
  });
}

export function useFanInCancelMutation(projectId: string, compId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => faninApi.cancelFanIn(projectId, compId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: faninKeys.detail(projectId, compId),
      });
    },
  });
}
