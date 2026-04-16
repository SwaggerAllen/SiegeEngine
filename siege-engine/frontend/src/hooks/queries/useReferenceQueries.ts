import { useQuery } from '@tanstack/react-query';
import * as refsApi from '../../api/references';

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
    queryFn: () => refsApi.getReferences(projectId),
    enabled: !!projectId,
  });
}

/**
 * Fetch one reference's full detail plus its pending draft and
 * outgoing / incoming edges.
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
    queryFn: () => refsApi.getReference(projectId, refId as string),
    enabled: !!projectId && !!refId,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.generation_status === 'running' ? 2000 : false;
    },
  });
}
