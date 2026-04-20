import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as queueApi from '../../api/queue';
import type { Instruction } from '../../api/queue';

/**
 * Queue query + mutation hooks. `queueKeys.project(projectId)` is
 * the single key every queue consumer reads from; mutations
 * invalidate it on success.
 *
 * An apply also invalidates the structure query because the apply
 * job emits events that mutate projections (NodeRenamed,
 * EdgeCreated, etc.) — so the DAG and nav-tree need a refresh.
 */
export const queueKeys = {
  all: ['queue'] as const,
  project: (projectId: string) => ['queue', projectId] as const,
};

export function useProjectQueue(projectId: string) {
  return useQuery({
    queryKey: queueKeys.project(projectId),
    queryFn: () => queueApi.getQueue(projectId),
    enabled: !!projectId,
  });
}

export function useEnqueueInstruction(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (instruction: Instruction) =>
      queueApi.enqueueInstruction(projectId, instruction),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queueKeys.project(projectId) });
    },
  });
}

export function useApplyQueue(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => queueApi.applyQueue(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queueKeys.project(projectId) });
      qc.invalidateQueries({ queryKey: ['structure', projectId] });
    },
  });
}

export function useDiscardAll(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => queueApi.discardAll(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queueKeys.project(projectId) });
    },
  });
}

export function useDiscardOne(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (instructionId: string) =>
      queueApi.discardOne(projectId, instructionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queueKeys.project(projectId) });
    },
  });
}

export function useRetryInstruction(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (instructionId: string) =>
      queueApi.retryInstruction(projectId, instructionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queueKeys.project(projectId) });
    },
  });
}
