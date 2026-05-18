import { useMutation, useQueryClient, type Query } from '@tanstack/react-query';
import type { BootstrapResponse } from '../api/bootstrapApi';

/**
 * Conditional refetch interval for per-tier detail queries.
 *
 * Phase 3 migration: the SSE-driven dashboard is gone, and there
 * is no live attempt counter to poll for either — generation runs
 * inside Claude Code on the user's device, not on the server. This
 * helper is now a no-op that always returns ``false`` so consumers
 * keep typechecking while polling stays off. Will be removed
 * outright when the per-tier query hooks are repointed at the new
 * MCP HTTP endpoints in a follow-up patch.
 */
export function runningRefetchInterval<
  T extends { generation_status?: string } | undefined,
>(_query: Query<T, Error, T, readonly unknown[]>): number | false {
  // Reference the parameter so eslint doesn't flag it; the
  // generic signature has to stay for downstream typings.
  void _query;
  return false;
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
  /**
   * Variadic signature: leading positional ``scopeIds`` followed
   * by the ``feedback`` string, plus an optional trailing number
   * ``autoRevisionsRequested`` that opts this regen into the
   * Phase 12 auto-revision loop. Tiers that don't wire the count
   * pass only the string and behave as before.
   */
  postFeedback: (...args: Array<string | number>) => Promise<{ job_id: string }>;
  approveDraft: (...args: string[]) => Promise<unknown>;
  discardDraft: (...args: string[]) => Promise<unknown>;
  cancelGeneration: (...args: string[]) => Promise<unknown>;
  resetTier?: (...args: string[]) => Promise<unknown>;
  retryReview?: (...args: string[]) => Promise<unknown>;
}

/**
 * Input shape for the feedback mutation. Passing a plain string
 * is equivalent to ``{ feedback: value }`` — existing callers
 * stay unchanged. Callers that want auto-revision on the regen
 * pass ``{ feedback, autoRevisionsRequested }`` instead.
 */
export type FeedbackMutationInput =
  | string
  | { feedback: string; autoRevisionsRequested?: number };

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
      mutationFn: (input: FeedbackMutationInput) => {
        const feedback = typeof input === 'string' ? input : input.feedback;
        const autoRevisionsRequested =
          typeof input === 'string' ? 0 : (input.autoRevisionsRequested ?? 0);
        if (autoRevisionsRequested > 0) {
          return apiFns.postFeedback(
            ...scopeIds,
            feedback,
            autoRevisionsRequested,
          );
        }
        return apiFns.postFeedback(...scopeIds, feedback);
      },
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

  function useReviewRetryMutation(...scopeIds: string[]) {
    const queryClient = useQueryClient();
    return useMutation({
      mutationKey: [tierName, 'retry-review', ...scopeIds],
      mutationFn: () => apiFns.retryReview?.(...scopeIds) ?? Promise.resolve(),
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: keys.detail(...scopeIds) });
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
    useReviewRetryMutation,
  };
}
