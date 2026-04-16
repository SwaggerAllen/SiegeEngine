import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as reqsApi from '../../api/requirements';
import type { ReqsResponse } from '../../api/requirements';
import { requirementsKeys } from '../queries/useRequirementsQueries';

// Parallel shape to useExpansionMutations. Each mutation optimistically
// nudges the query cache so the UI feels responsive without waiting
// for the next poll.

export function useFeedbackMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['requirements', 'feedback', projectId],
    mutationFn: (feedback: string) => reqsApi.postFeedback(projectId, feedback),
    onSuccess: () => {
      queryClient.setQueryData<ReqsResponse>(
        requirementsKeys.detail(projectId),
        (prev) =>
          prev
            ? { ...prev, generation_status: 'running', last_error: null }
            : prev
      );
      queryClient.invalidateQueries({ queryKey: requirementsKeys.detail(projectId) });
    },
  });
}

export function useApproveMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['requirements', 'approve', projectId],
    mutationFn: (draftId: string) => reqsApi.approveDraft(projectId, draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: requirementsKeys.detail(projectId) });
    },
  });
}

export function useDiscardMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['requirements', 'discard', projectId],
    mutationFn: (draftId: string) => reqsApi.discardDraft(projectId, draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: requirementsKeys.detail(projectId) });
    },
  });
}

export function useCancelGenerationMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['requirements', 'cancel', projectId],
    mutationFn: () => reqsApi.cancelGeneration(projectId),
    onSuccess: () => {
      queryClient.setQueryData<ReqsResponse>(
        requirementsKeys.detail(projectId),
        (prev) =>
          prev
            ? { ...prev, generation_status: 'idle', generation_started_at: null }
            : prev
      );
      queryClient.invalidateQueries({ queryKey: requirementsKeys.detail(projectId) });
    },
  });
}

export function useResetMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['requirements', 'reset', projectId],
    mutationFn: () => reqsApi.resetRequirements(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: requirementsKeys.all });
    },
  });
}
