import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as subcomparchApi from '../../api/subcomparch';
import type { SubcomparchResponse } from '../../api/subcomparch';
import { subcomparchKeys } from '../queries/useSubcomparchQueries';

export function useSubcomparchFeedbackMutation(
  projectId: string,
  parentCompId: string,
  subId: string
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['subcomparch', 'feedback', projectId, parentCompId, subId],
    mutationFn: (feedback: string) =>
      subcomparchApi.postFeedback(projectId, parentCompId, subId, feedback),
    onSuccess: () => {
      queryClient.setQueryData<SubcomparchResponse>(
        subcomparchKeys.detail(projectId, parentCompId, subId),
        (prev) =>
          prev
            ? { ...prev, generation_status: 'running', last_error: null }
            : prev
      );
      queryClient.invalidateQueries({
        queryKey: subcomparchKeys.detail(projectId, parentCompId, subId),
      });
    },
  });
}

export function useSubcomparchApproveMutation(
  projectId: string,
  parentCompId: string,
  subId: string
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['subcomparch', 'approve', projectId, parentCompId, subId],
    mutationFn: (draftId: string) =>
      subcomparchApi.approveDraft(projectId, parentCompId, subId, draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: subcomparchKeys.detail(projectId, parentCompId, subId),
      });
    },
  });
}

export function useSubcomparchDiscardMutation(
  projectId: string,
  parentCompId: string,
  subId: string
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['subcomparch', 'discard', projectId, parentCompId, subId],
    mutationFn: (draftId: string) =>
      subcomparchApi.discardDraft(projectId, parentCompId, subId, draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: subcomparchKeys.detail(projectId, parentCompId, subId),
      });
    },
  });
}
