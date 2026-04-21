import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  applyQueue,
  discardPending,
  enqueueInstruction,
  type ApplyResponse,
  type DiscardResponse,
  type EnqueueResponse,
  type Instruction,
} from '../../api/queue';
import { announceInstruction } from '../../lib/queueAnnounce';
import { queueKeys } from '../queries/useQueueQueries';

/**
 * Phase 11 — queue mutations. Each wraps its backend fetcher,
 * invalidates ``queueKeys.project(projectId)`` on success, and
 * returns the raw backend response. The SSE stream also
 * invalidates the queue list on the corresponding queue event,
 * so these optimistic-ish invalidations are belt-and-braces —
 * the panel refetches quickly even if SSE is momentarily down.
 */

export function useEnqueueInstructionMutation(projectId: string) {
  const qc = useQueryClient();
  return useMutation<EnqueueResponse, unknown, Instruction>({
    mutationFn: (instruction) => enqueueInstruction(projectId, instruction),
    onSuccess: (_resp, instruction) => {
      void qc.invalidateQueries({ queryKey: queueKeys.project(projectId) });
      // PR-11c — screen-reader-friendly confirmation for the
      // graph editors' tap-driven enqueues.
      announceInstruction(instruction);
    },
  });
}

export function useDiscardPendingMutation(projectId: string) {
  const qc = useQueryClient();
  return useMutation<DiscardResponse, unknown, number | undefined>({
    mutationFn: (sequence) => discardPending(projectId, sequence),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queueKeys.project(projectId) });
    },
  });
}

export function useApplyQueueMutation(projectId: string) {
  const qc = useQueryClient();
  return useMutation<ApplyResponse, unknown, void>({
    mutationFn: () => applyQueue(projectId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queueKeys.project(projectId) });
    },
  });
}
