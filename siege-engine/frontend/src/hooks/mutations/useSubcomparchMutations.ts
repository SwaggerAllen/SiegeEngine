import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as subcomparchApi from '../../api/subcomparch';
import type { SubcomparchResponse } from '../../api/subcomparch';
import { decompositionGraphKeys } from '../queries/useDecompositionGraph';
import { subcomparchKeys } from '../queries/useSubcomparchQueries';
import { componentsKeys } from '../queries/useSysarchQueries';

// Approve / discard / feedback all invalidate the components
// list and decomposition graph queries in addition to the
// subcomparch detail query, so Phase 6 waiting-on-approval
// badges in the DAG re-fetch when a subcomparch draft is
// created or resolved. The sysarch-view badges only surface
// top-level-comp pending drafts today, so they don't strictly
// need the invalidation — but keeping the flush symmetric with
// the other mutation paths avoids a class of "I forgot to wire
// up view N" bugs later.

function invalidateWaitingIndicators(
  queryClient: ReturnType<typeof useQueryClient>,
  projectId: string
) {
  queryClient.invalidateQueries({ queryKey: componentsKeys.list(projectId) });
  queryClient.invalidateQueries({
    queryKey: decompositionGraphKeys.detail(projectId),
  });
}

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
      invalidateWaitingIndicators(queryClient, projectId);
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
      invalidateWaitingIndicators(queryClient, projectId);
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
      invalidateWaitingIndicators(queryClient, projectId);
    },
  });
}

export function useSubcomparchCancelGenerationMutation(
  projectId: string,
  parentCompId: string,
  subId: string
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['subcomparch', 'cancel', projectId, parentCompId, subId],
    mutationFn: () =>
      subcomparchApi.cancelGeneration(projectId, parentCompId, subId),
    onSuccess: () => {
      queryClient.setQueryData<SubcomparchResponse>(
        subcomparchKeys.detail(projectId, parentCompId, subId),
        (prev) =>
          prev
            ? { ...prev, generation_status: 'idle', generation_started_at: null }
            : prev
      );
      queryClient.invalidateQueries({
        queryKey: subcomparchKeys.detail(projectId, parentCompId, subId),
      });
      invalidateWaitingIndicators(queryClient, projectId);
    },
  });
}
