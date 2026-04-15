import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as subreqsApi from '../../api/subreqs';
import type { SubreqsResponse } from '../../api/subreqs';
import { decompositionGraphKeys } from '../queries/useDecompositionGraph';
import { componentsKeys } from '../queries/useSysarchQueries';
import { subreqsKeys } from '../queries/useSubreqsQueries';

// Per-component mutations — each takes componentId at creation
// time so call sites stay clean (thin panel wrappers).
//
// Approve / discard / feedback all invalidate the components list
// and decomposition graph queries in addition to the subreqs
// detail query: the components list carries the waiting-on-
// approval badges rendered in the sysarch view, and the
// decomposition graph carries the same badges on comp_* nodes
// in the DAG view (Phase 6 waiting indicators). A mutation here
// creates or resolves a pending subreqs draft and the badge
// state flips, so the dependent queries need to re-fetch.

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
      invalidateWaitingIndicators(queryClient, projectId);
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
      invalidateWaitingIndicators(queryClient, projectId);
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
      invalidateWaitingIndicators(queryClient, projectId);
    },
  });
}
