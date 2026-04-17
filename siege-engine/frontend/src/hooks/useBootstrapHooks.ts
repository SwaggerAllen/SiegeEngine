import { useMutation, useQueryClient, type Query } from '@tanstack/react-query';
import type { BootstrapResponse } from '../api/bootstrapApi';

/**
 * Conditional refetch interval for per-tier detail queries.
 *
 * SSE drives refetches for committed events (draft / content /
 * offset advances), but attempt-counter progress is stashed on
 * the live Job row's payload and never produces an event. While
 * a tier is actively generating, poll every 2s so the
 * ``current_attempt`` / ``max_attempts`` fields stay fresh for
 * the generation spinner. Idle tiers stay push-only.
 */
export function runningRefetchInterval<
  T extends { generation_status?: string } | undefined,
>(query: Query<T, Error, T, readonly unknown[]>): number | false {
  return query.state.data?.generation_status === 'running' ? 2000 : false;
}

export interface BootstrapKeyFactory {
  all: readonly string[];
  detail: (...scopeIds: string[]) => readonly string[];
}

export function makeBootstrapKeys(tierName: string): BootstrapKeyFactory {
  const all = [tierName] as const;
  return {
    all,
    detail: (...scopeIds: string[]) => [...all, ...scopeIds] as const,
  };
}

export interface MutationApiFns {
  postFeedback: (...args: string[]) => Promise<{ job_id: string }>;
  approveDraft: (...args: string[]) => Promise<unknown>;
  discardDraft: (...args: string[]) => Promise<unknown>;
  cancelGeneration: (...args: string[]) => Promise<unknown>;
  resetTier?: (...args: string[]) => Promise<unknown>;
}

export function makeBootstrapMutations(
  tierName: string,
  apiFns: MutationApiFns,
  keys: BootstrapKeyFactory,
  extraInvalidations?: (
    queryClient: ReturnType<typeof useQueryClient>,
    projectId: string
  ) => void
) {
  function useFeedbackMutation(...scopeIds: string[]) {
    const queryClient = useQueryClient();
    return useMutation({
      mutationKey: [tierName, 'feedback', ...scopeIds],
      mutationFn: (feedback: string) => apiFns.postFeedback(...scopeIds, feedback),
      onSuccess: () => {
        queryClient.setQueryData<BootstrapResponse>(
          keys.detail(...scopeIds),
          (prev) =>
            prev
              ? { ...prev, generation_status: 'running' as const, last_error: null }
              : prev
        );
        queryClient.invalidateQueries({ queryKey: keys.detail(...scopeIds) });
        extraInvalidations?.(queryClient, scopeIds[0]);
      },
    });
  }

  function useApproveMutation(...scopeIds: string[]) {
    const queryClient = useQueryClient();
    return useMutation({
      mutationKey: [tierName, 'approve', ...scopeIds],
      mutationFn: (draftId: string) => apiFns.approveDraft(...scopeIds, draftId),
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: keys.detail(...scopeIds) });
        extraInvalidations?.(queryClient, scopeIds[0]);
      },
    });
  }

  function useDiscardMutation(...scopeIds: string[]) {
    const queryClient = useQueryClient();
    return useMutation({
      mutationKey: [tierName, 'discard', ...scopeIds],
      mutationFn: (draftId: string) => apiFns.discardDraft(...scopeIds, draftId),
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: keys.detail(...scopeIds) });
        extraInvalidations?.(queryClient, scopeIds[0]);
      },
    });
  }

  function useCancelGenerationMutation(...scopeIds: string[]) {
    const queryClient = useQueryClient();
    return useMutation({
      mutationKey: [tierName, 'cancel', ...scopeIds],
      mutationFn: () => apiFns.cancelGeneration(...scopeIds),
      onSuccess: () => {
        queryClient.setQueryData<BootstrapResponse>(
          keys.detail(...scopeIds),
          (prev) =>
            prev
              ? {
                  ...prev,
                  generation_status: 'idle' as const,
                  generation_started_at: null,
                }
              : prev
        );
        queryClient.invalidateQueries({ queryKey: keys.detail(...scopeIds) });
        extraInvalidations?.(queryClient, scopeIds[0]);
      },
    });
  }

  function useResetMutation(...scopeIds: string[]) {
    const queryClient = useQueryClient();
    return useMutation({
      mutationKey: [tierName, 'reset', ...scopeIds],
      mutationFn: () => apiFns.resetTier?.(...scopeIds) ?? Promise.resolve(),
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: keys.all });
        extraInvalidations?.(queryClient, scopeIds[0]);
      },
    });
  }

  return {
    useFeedbackMutation,
    useApproveMutation,
    useDiscardMutation,
    useCancelGenerationMutation,
    useResetMutation,
  };
}
