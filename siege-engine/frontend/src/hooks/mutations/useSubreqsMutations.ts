import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as subreqsApi from '../../api/subreqs';
import type { SubreqsResponse } from '../../api/subreqs';
import { subreqsKeys } from '../queries/useSubreqsQueries';

// Per-component mutations — each takes componentId at creation
// time so call sites stay clean (thin panel wrappers).

export function useFeedbackMutation(projectId: string, componentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['subreqs', 'feedback', projectId, componentId],
    mutationFn: (feedback: string) =>
      subreqsApi.postFeedback(projectId, componentId, feedback),
    onSuccess: () => {
      queryClient.setQueryData<SubreqsResponse>(
        subreqsKeys.detail(projectId, componentId),
        (prev) =>
          prev ? { ...prev, generation_status: 'running', last_error: null } : prev
      );
      queryClient.invalidateQueries({
        queryKey: subreqsKeys.detail(projectId, componentId),
      });
    },
  });
}

export function useApproveMutation(projectId: string, componentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['subreqs', 'approve', projectId, componentId],
    mutationFn: (draftId: string) =>
      subreqsApi.approveDraft(projectId, componentId, draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: subreqsKeys.detail(projectId, componentId),
      });
    },
  });
}

export function useDiscardMutation(projectId: string, componentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['subreqs', 'discard', projectId, componentId],
    mutationFn: (draftId: string) =>
      subreqsApi.discardDraft(projectId, componentId, draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: subreqsKeys.detail(projectId, componentId),
      });
    },
  });
}
