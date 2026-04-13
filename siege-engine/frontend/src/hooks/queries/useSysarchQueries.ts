import { useQuery } from '@tanstack/react-query';
import * as sysarchApi from '../../api/sysarch';

export const sysarchKeys = {
  all: ['sysarch'] as const,
  detail: (projectId: string) => [...sysarchKeys.all, projectId] as const,
};

export const componentsKeys = {
  all: ['components'] as const,
  list: (projectId: string) => [...componentsKeys.all, 'list', projectId] as const,
};

export const policiesKeys = {
  all: ['policies'] as const,
  list: (projectId: string) => [...policiesKeys.all, 'list', projectId] as const,
};

/**
 * Fetch the project's sysarch node — the four-state panel reads
 * through this. Polls every 2s while generation is running.
 * Mirrors ``useExpansion`` and ``useRequirements``.
 */
export function useSysarch(projectId: string) {
  return useQuery({
    queryKey: sysarchKeys.detail(projectId),
    queryFn: () => sysarchApi.getSysarch(projectId),
    enabled: !!projectId,
    refetchInterval: (query) =>
      query.state.data?.generation_status === 'running' ? 2000 : false,
  });
}

/**
 * Fetch the project's top-level ``comp_*`` nodes.
 *
 * Same ``mintPending`` pattern as the feature / responsibility
 * lists — while the mint handler might still be populating the
 * list, the caller passes ``true`` and the hook polls every 2s
 * until the list becomes non-empty.
 */
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

/**
 * Fetch the project's ``policy_*`` nodes (top-level + component-
 * local once Phase 4 lands).
 */
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
