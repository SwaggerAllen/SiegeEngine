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
      refetchOnWindowFocus: 'always',
    },
    mutations: {
      onError: handleMutationError as never,
    },
  },
});

// Wire up global query error handler
queryClient.getQueryCache().config.onError = handleQueryError as never;

// Patch the low-level queryCache.clear() so we catch ALL cache nukes,
// whether called via queryClient.clear() or queryClient.getQueryCache().clear().
const _qc = queryClient.getQueryCache();
const _origCacheClear = _qc.clear.bind(_qc);
_qc.clear = () => {
  const stack = new Error('queryCache.clear() called').stack ?? 'no stack';
  debugError('TQ.clear', stack);
  return _origCacheClear();
};
const _origRemove = queryClient.removeQueries.bind(queryClient);
queryClient.removeQueries = (...args) => {
  const stack = new Error('queryClient.removeQueries() called').stack ?? 'no stack';
  debugError('TQ.removeQueries', stack);
  return _origRemove(...args);
};

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
