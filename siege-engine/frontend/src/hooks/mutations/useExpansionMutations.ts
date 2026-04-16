import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as expansionApi from '../../api/expansion';
import type { ExpansionResponse } from '../../api/expansion';
import { expansionKeys } from '../queries/useExpansionQueries';

export function useFeedbackMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['expansion', 'feedback', projectId],
    mutationFn: (feedback: string) => expansionApi.postFeedback(projectId, feedback),
    onSuccess: () => {
      // Optimistically mark the query as running so polling kicks in
      // immediately, without waiting for the next server round-trip.
      queryClient.setQueryData<ExpansionResponse>(
        expansionKeys.detail(projectId),
        (prev) =>
          prev
            ? { ...prev, generation_status: 'running', last_error: null }
            : prev
      );
      queryClient.invalidateQueries({ queryKey: expansionKeys.detail(projectId) });
    },
  });
}

export function useApproveMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['expansion', 'approve', projectId],
    mutationFn: (draftId: string) => expansionApi.approveDraft(projectId, draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: expansionKeys.detail(projectId) });
    },
  });
}

export function useDiscardMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['expansion', 'discard', projectId],
    mutationFn: (draftId: string) => expansionApi.discardDraft(projectId, draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: expansionKeys.detail(projectId) });
    },
  });
}

export function useCancelGenerationMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['expansion', 'cancel', projectId],
    mutationFn: () => expansionApi.cancelGeneration(projectId),
    onSuccess: () => {
      // Optimistically flip back to idle so the Stop button stops
      // showing and the panel re-renders into the feedback /
      // accept / reject state over any remaining pending draft
      // without waiting for the next poll tick.
      queryClient.setQueryData<ExpansionResponse>(
        expansionKeys.detail(projectId),
        (prev) =>
          prev
            ? { ...prev, generation_status: 'idle', generation_started_at: null }
            : prev
      );
      queryClient.invalidateQueries({ queryKey: expansionKeys.detail(projectId) });
    },
  });
}
