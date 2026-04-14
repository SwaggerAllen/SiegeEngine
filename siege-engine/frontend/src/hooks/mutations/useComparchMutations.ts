import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as comparchApi from '../../api/comparch';
import type { ComparchResponse } from '../../api/comparch';
import { comparchKeys } from '../queries/useComparchQueries';

export function useFeedbackMutation(projectId: string, componentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['comparch', 'feedback', projectId, componentId],
    mutationFn: (feedback: string) =>
      comparchApi.postFeedback(projectId, componentId, feedback),
    onSuccess: () => {
      queryClient.setQueryData<ComparchResponse>(
        comparchKeys.detail(projectId, componentId),
        (prev) =>
          prev ? { ...prev, generation_status: 'running', last_error: null } : prev
      );
      queryClient.invalidateQueries({
        queryKey: comparchKeys.detail(projectId, componentId),
      });
    },
  });
}

export function useApproveMutation(projectId: string, componentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['comparch', 'approve', projectId, componentId],
    mutationFn: (draftId: string) =>
      comparchApi.approveDraft(projectId, componentId, draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: comparchKeys.detail(projectId, componentId),
      });
    },
  });
}

export function useDiscardMutation(projectId: string, componentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['comparch', 'discard', projectId, componentId],
    mutationFn: (draftId: string) =>
      comparchApi.discardDraft(projectId, componentId, draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: comparchKeys.detail(projectId, componentId),
      });
    },
  });
}
