import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as sysarchApi from '../../api/sysarch';
import type { SysarchResponse } from '../../api/sysarch';
import { sysarchKeys } from '../queries/useSysarchQueries';

// Parallel to useExpansionMutations / useRequirementsMutations.

export function useFeedbackMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['sysarch', 'feedback', projectId],
    mutationFn: (feedback: string) => sysarchApi.postFeedback(projectId, feedback),
    onSuccess: () => {
      queryClient.setQueryData<SysarchResponse>(
        sysarchKeys.detail(projectId),
        (prev) =>
          prev ? { ...prev, generation_status: 'running', last_error: null } : prev
      );
      queryClient.invalidateQueries({ queryKey: sysarchKeys.detail(projectId) });
    },
  });
}

export function useApproveMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['sysarch', 'approve', projectId],
    mutationFn: (draftId: string) => sysarchApi.approveDraft(projectId, draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sysarchKeys.detail(projectId) });
    },
  });
}

export function useDiscardMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['sysarch', 'discard', projectId],
    mutationFn: (draftId: string) => sysarchApi.discardDraft(projectId, draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sysarchKeys.detail(projectId) });
    },
  });
}

export function useCancelGenerationMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['sysarch', 'cancel', projectId],
    mutationFn: () => sysarchApi.cancelGeneration(projectId),
    onSuccess: () => {
      queryClient.setQueryData<SysarchResponse>(
        sysarchKeys.detail(projectId),
        (prev) =>
          prev
            ? { ...prev, generation_status: 'idle', generation_started_at: null }
            : prev
      );
      queryClient.invalidateQueries({ queryKey: sysarchKeys.detail(projectId) });
    },
  });
}
