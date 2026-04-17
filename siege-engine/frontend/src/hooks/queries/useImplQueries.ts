import { useQuery } from '@tanstack/react-query';
import * as implApi from '../../api/impl';
import { makeBootstrapKeys } from '../useBootstrapHooks';

// Phase 8: two impl query hooks, one per URL shape. Both share
// a single `impl` key factory rooted on the owner id so the
// TanStack cache key scopes identically to the backend's
// IMPL_CONFIG (single scope key: owner_id).

export const implKeys = makeBootstrapKeys('impl');

/**
 * Fetch the impl for an un-fanned-out top-level component.
 * URL: ``/projects/:id/components/:compId/impl``.
 */
export function useImplTopLevel(projectId: string, compId: string) {
  return useQuery({
    queryKey: implKeys.detail(projectId, compId),
    queryFn: () => implApi.getImplTopLevel(projectId, compId),
    enabled: !!projectId && !!compId,
    refetchInterval: (query) =>
      query.state.data?.generation_status === 'running' ? 2000 : false,
  });
}

/**
 * Fetch the impl for a per-subcomponent leaf.
 * URL: ``/projects/:id/components/:parentCompId/subcomponents/:subId/impl``.
 */
export function useImplSub(
  projectId: string,
  parentCompId: string,
  subId: string,
) {
  return useQuery({
    // The detail key uses the owner id (subId) as the scope
    // value so top-level and sub impls share one cache partition
    // keyed by their owner, matching IMPL_CONFIG on the backend.
    queryKey: implKeys.detail(projectId, subId),
    queryFn: () => implApi.getImplSub(projectId, parentCompId, subId),
    enabled: !!projectId && !!parentCompId && !!subId,
    refetchInterval: (query) =>
      query.state.data?.generation_status === 'running' ? 2000 : false,
  });
}
