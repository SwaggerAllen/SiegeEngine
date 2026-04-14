import { useQuery } from '@tanstack/react-query';
import * as subcomparchApi from '../../api/subcomparch';

export const subcomparchKeys = {
  all: ['subcomparch'] as const,
  detail: (projectId: string, parentCompId: string, subId: string) =>
    [...subcomparchKeys.all, projectId, parentCompId, subId] as const,
};

/**
 * Fetch a single subcomponent's subcomparch draft state — four-
 * state panel reads through this. Polls every 2s while
 * generation is running. Scoped by the
 * ``(projectId, parentCompId, subId)`` triple because
 * subcomparch routes are nested one level deeper than comparch.
 */
export function useSubcomparch(
  projectId: string,
  parentCompId: string,
  subId: string
) {
  return useQuery({
    queryKey: subcomparchKeys.detail(projectId, parentCompId, subId),
    queryFn: () => subcomparchApi.getSubcomparch(projectId, parentCompId, subId),
    enabled: !!projectId && !!parentCompId && !!subId,
    refetchInterval: (query) =>
      query.state.data?.generation_status === 'running' ? 2000 : false,
  });
}
