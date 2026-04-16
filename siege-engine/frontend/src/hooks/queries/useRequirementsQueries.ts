import { useQuery } from '@tanstack/react-query';
import * as reqsApi from '../../api/requirements';
import { makeBootstrapKeys } from '../useBootstrapHooks';

export const requirementsKeys = makeBootstrapKeys('requirements');

export const responsibilitiesKeys = {
  all: ['responsibilities'] as const,
  list: (projectId: string) => [...responsibilitiesKeys.all, 'list', projectId] as const,
};

export function useRequirements(projectId: string) {
  return useQuery({
    queryKey: requirementsKeys.detail(projectId),
    queryFn: () => reqsApi.getRequirements(projectId),
    enabled: !!projectId,
    refetchInterval: (query) =>
      query.state.data?.generation_status === 'running' ? 2000 : false,
  });
}

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
