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
  });
}

export function useComponents(projectId: string) {
  return useQuery({
    queryKey: componentsKeys.list(projectId),
    queryFn: () => sysarchApi.getComponents(projectId),
    enabled: !!projectId,
  });
}

export function usePolicies(projectId: string) {
  return useQuery({
    queryKey: policiesKeys.list(projectId),
    queryFn: () => sysarchApi.getPolicies(projectId),
    enabled: !!projectId,
  });
}
