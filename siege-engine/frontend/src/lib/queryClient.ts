import { QueryClient, type Mutation, type Query } from '@tanstack/react-query';
import { useErrorLogStore } from '../store/errorLogStore';
import { debugError } from './debugLog';

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
      refetchOnWindowFocus: true,
    },
    mutations: {
      onError: handleMutationError as never,
    },
  },
});

// Wire up global query error handler
queryClient.getQueryCache().config.onError = handleQueryError as never;
