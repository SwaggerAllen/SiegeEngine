import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as comparchApi from '../../api/comparch';
import type { ComparchResponse } from '../../api/comparch';
import { comparchKeys } from '../queries/useComparchQueries';
import { decompositionGraphKeys } from '../queries/useDecompositionGraph';
import { componentsKeys } from '../queries/useSysarchQueries';

// Approve / discard / feedback all invalidate the components list
// and decomposition graph queries in addition to the comparch
// detail query, so Phase 6 waiting-on-approval badges in the
// sysarch view and DAG re-fetch when a comparch draft is created
// or resolved.

function invalidateWaitingIndicators(
  queryClient: ReturnType<typeof useQueryClient>,
  projectId: string
) {
  queryClient.invalidateQueries({ queryKey: componentsKeys.list(projectId) });
  queryClient.invalidateQueries({
    queryKey: decompositionGraphKeys.detail(projectId),
  });
}

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
      invalidateWaitingIndicators(queryClient, projectId);
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
      invalidateWaitingIndicators(queryClient, projectId);
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
      invalidateWaitingIndicators(queryClient, projectId);
    },
  });
}
