import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as sysarchApi from '../../api/sysarch';
import type { SysarchResponse } from '../../api/sysarch';
import {
  componentsKeys,
  policiesKeys,
  sysarchKeys,
} from '../queries/useSysarchQueries';

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

export function useResetMutation(projectId: string) {
  // Destructive reset of an approved sysarch node. Unlike the other
  // mutations this one invalidates a much broader set of query keys
  // because the cascade touches components, policies, subreqs, and
  // downstream drafts for every comp in the project. Simplest move
  // is to invalidate the whole 'sysarch' prefix which blows every
  // cached query for the tier away and forces a refetch on next use.
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['sysarch', 'reset', projectId],
    mutationFn: () => sysarchApi.resetSysarch(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sysarchKeys.all });
      // Components + policies list queries also live under their
      // own keys — invalidate them so the approved-state UI flips
      // back to the empty pre-mint state on the next poll.
      queryClient.invalidateQueries({ queryKey: componentsKeys.list(projectId) });
      queryClient.invalidateQueries({ queryKey: policiesKeys.list(projectId) });
    },
  });
}
