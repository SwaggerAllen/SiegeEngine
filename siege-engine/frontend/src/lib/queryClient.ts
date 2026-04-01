import { QueryClient, type Mutation, type Query } from '@tanstack/react-query';
import { useErrorLogStore } from '../store/errorLogStore';
import { debugError } from './debugLog';

function handleQueryError(error: Error, query: Query) {
  const key = query.queryKey.join('.');
  debugError(`TQ.${key}`, error);
  useErrorLogStore.getState().pushError(`query.${key}`, error);
}

function handleMutationCacheError(
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
      refetchOnWindowFocus: true,
    },
  },
});

// Wire up global query error handler
queryClient.getQueryCache().config.onError = handleQueryError as never;

// Wire up global mutation error handler via the MutationCache,
// which provides the mutation object as the 4th argument.
// (defaultOptions.mutations.onError only receives (error, variables, context)
// and does NOT include the mutation — accessing mutation.options there crashes.)
queryClient.getMutationCache().config.onError = handleMutationCacheError as never;

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

// TQ cache event logging disabled — the per-event overhead (JSON.stringify,
// object allocation, buffer growth) adds significant main-thread pressure
// during pipeline runs with frequent WS-triggered invalidations.
// Re-enable for debugging by uncommenting below.
//
// queryClient.getQueryCache().subscribe((event) => {
//   if (!event?.query) return;
//   const q = event.query;
//   recordTQEvent({
//     ts: new Date().toISOString().slice(11, 23),
//     type: event.type,
//     key: JSON.stringify(q.queryKey),
//     status: q.state.status,
//     fetchStatus: q.state.fetchStatus,
//     dataUpdatedAt: q.state.dataUpdatedAt,
//     observers: q.getObserversCount(),
//   });
// });
