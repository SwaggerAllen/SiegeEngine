import { useQuery } from '@tanstack/react-query';
import * as sysarchApi from '../../api/sysarch';
import { makeBootstrapKeys } from '../useBootstrapHooks';

export const sysarchKeys = makeBootstrapKeys('sysarch');

export const componentsKeys = {
  all: ['components'] as const,
  list: (projectId: string) => [...componentsKeys.all, 'list', projectId] as const,
};

export const policiesKeys = {
  all: ['policies'] as const,
  list: (projectId: string) => [...policiesKeys.all, 'list', projectId] as const,
};

export function useSysarch(projectId: string) {
  return useQuery({
    queryKey: sysarchKeys.detail(projectId),
    queryFn: () => sysarchApi.getSysarch(projectId),
    enabled: !!projectId,
    refetchInterval: (query) =>
      query.state.data?.generation_status === 'running' ? 2000 : false,
  });
}

export function useComponents(projectId: string, mintPending: boolean = false) {
  return useQuery({
    queryKey: componentsKeys.list(projectId),
    queryFn: () => sysarchApi.getComponents(projectId),
    enabled: !!projectId,
    refetchInterval: (query) => {
      if (!mintPending) return false;
      const hasComps = (query.state.data?.components.length ?? 0) > 0;
      return hasComps ? false : 2000;
    },
  });
}

export function usePolicies(projectId: string, mintPending: boolean = false) {
  return useQuery({
    queryKey: policiesKeys.list(projectId),
    queryFn: () => sysarchApi.getPolicies(projectId),
    enabled: !!projectId,
    refetchInterval: (query) => {
      if (!mintPending) return false;
      const hasPolicies = (query.state.data?.policies.length ?? 0) > 0;
      return hasPolicies ? false : 2000;
    },
  });
}
