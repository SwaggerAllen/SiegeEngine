import { useQuery } from '@tanstack/react-query';
import * as subreqsApi from '../../api/subreqs';

export const subreqsKeys = {
  all: ['subreqs'] as const,
  detail: (projectId: string, compId: string) =>
    [...subreqsKeys.all, projectId, compId] as const,
};

export const subresponsibilitiesKeys = {
  all: ['subresponsibilities'] as const,
  list: (projectId: string, compId: string) =>
    [...subresponsibilitiesKeys.all, 'list', projectId, compId] as const,
};

/**
 * Fetch a single component's subreqs node — the four-state panel
 * reads through this. Polls every 2s while generation is running.
 */
export function useSubreqs(projectId: string, componentId: string) {
  return useQuery({
    queryKey: subreqsKeys.detail(projectId, componentId),
    queryFn: () => subreqsApi.getSubreqs(projectId, componentId),
    enabled: !!projectId && !!componentId,
    refetchInterval: (query) =>
      query.state.data?.generation_status === 'running' ? 2000 : false,
  });
}

/**
 * Fetch the subresponsibilities minted under a given component.
 *
 * Same ``mintPending`` polling pattern as the other list hooks.
 */
export function useSubresponsibilities(
  projectId: string,
  componentId: string,
  mintPending: boolean = false
) {
  return useQuery({
    queryKey: subresponsibilitiesKeys.list(projectId, componentId),
    queryFn: () => subreqsApi.getSubresponsibilities(projectId, componentId),
    enabled: !!projectId && !!componentId,
    refetchInterval: (query) => {
      if (!mintPending) return false;
      const hasSubresps = (query.state.data?.subresponsibilities.length ?? 0) > 0;
      return hasSubresps ? false : 2000;
    },
  });
}
