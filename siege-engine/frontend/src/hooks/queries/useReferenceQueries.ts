import { useQuery } from '@tanstack/react-query';
import { makeReferencesApi } from '../../api/references';

export const referenceKeys = {
  all: ['references'] as const,
  project: (projectId: string) =>
    [...referenceKeys.all, 'project', projectId] as const,
  detail: (projectId: string, refId: string) =>
    [...referenceKeys.all, 'detail', projectId, refId] as const,
};

/**
 * Fetch every reference in a project, ordered by name.
 */
export function useProjectReferences(projectId: string) {
  return useQuery({
    queryKey: referenceKeys.project(projectId),
    queryFn: () => makeReferencesApi(projectId).list(),
    enabled: !!projectId,
  });
}

/**
 * Fetch one reference's standard bootstrap-tier state plus its
 * outgoing / incoming reference edges.
 *
 * Polls while a generation is in flight so the UI reflects the
 * pending-draft transition without a manual refetch.
 */
export function useReferenceDetail(
  projectId: string,
  refId: string | null,
) {
  return useQuery({
    queryKey: referenceKeys.detail(projectId, refId ?? ''),
    queryFn: () => makeReferencesApi(projectId).getDetail(refId as string),
    enabled: !!projectId && !!refId,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.generation_status === 'running' ? 2000 : false;
    },
  });
}
