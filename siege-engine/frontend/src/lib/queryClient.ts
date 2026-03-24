import { QueryClient, type Mutation, type Query } from '@tanstack/react-query';
import { useErrorLogStore } from '../store/errorLogStore';
import { debugError, recordTQEvent } from './debugLog';

function handleQueryError(error: Error, query: Query) {
  const key = query.queryKey.join('.');
  debugError(`TQ.${key}`, error);
  useErrorLogStore.getState().pushError(`query.${key}`, error);
}

function handleMutationError(
  error: Error,
  _variables: unknown,
  _context: unknown,
  mutation: Mutation<unknown, unknown, unknown>,
) {
  const key = mutation.options.mutationKey?.join('.') ?? 'unknown';
  useErrorLogStore.getState().pushError(`mutation.${key}`, error);
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      throwOnError: false,
      refetchOnWindowFocus: false, // temporarily disabled to rule out as doom-loop cause
    },
    mutations: {
      onError: handleMutationError as never,
    },
  },
});

// Wire up global query error handler
queryClient.getQueryCache().config.onError = handleQueryError as never;

// Record all cache mutations to localStorage so they survive tab navigation
queryClient.getQueryCache().subscribe((event) => {
  if (!event?.query) return;
  const q = event.query;
  recordTQEvent({
    ts: new Date().toISOString().slice(11, 23),
    type: event.type,
    key: JSON.stringify(q.queryKey),
    status: q.state.status,
    fetchStatus: q.state.fetchStatus,
    dataUpdatedAt: q.state.dataUpdatedAt,
    observers: q.getObserversCount(),
  });
});
