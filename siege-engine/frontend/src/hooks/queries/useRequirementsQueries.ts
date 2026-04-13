import { useQuery } from '@tanstack/react-query';
import * as reqsApi from '../../api/requirements';

export const requirementsKeys = {
  all: ['requirements'] as const,
  detail: (projectId: string) => [...requirementsKeys.all, projectId] as const,
};

export const responsibilitiesKeys = {
  all: ['responsibilities'] as const,
  list: (projectId: string) => [...responsibilitiesKeys.all, 'list', projectId] as const,
};

/**
 * Fetch the project's reqs node — the four-state reqs panel reads
 * through this. Polls every 2s while generation is running; idle
 * otherwise. Mirrors ``useExpansion`` exactly.
 */
export function useRequirements(projectId: string) {
  return useQuery({
    queryKey: requirementsKeys.detail(projectId),
    queryFn: () => reqsApi.getRequirements(projectId),
    enabled: !!projectId,
    refetchInterval: (query) =>
      query.state.data?.generation_status === 'running' ? 2000 : false,
  });
}

/**
 * Fetch the project's top-level ``resp_*`` nodes.
 *
 * Same ``mintPending`` pattern as ``useFeatures``: while the reqs
 * mint handler might still be populating the list, the caller
 * passes ``true`` and the hook polls until the list becomes
 * non-empty.
 */
export function useResponsibilities(projectId: string, mintPending: boolean = false) {
  return useQuery({
    queryKey: responsibilitiesKeys.list(projectId),
    queryFn: () => reqsApi.getResponsibilities(projectId),
    enabled: !!projectId,
    refetchInterval: (query) => {
      if (!mintPending) return false;
      const hasResps = (query.state.data?.responsibilities.length ?? 0) > 0;
      return hasResps ? false : 2000;
    },
  });
}
