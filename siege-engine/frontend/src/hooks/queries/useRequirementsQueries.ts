import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import * as reqsApi from '../../api/requirements';
import { makeBootstrapKeys, runningRefetchInterval } from '../useBootstrapHooks';
import { useProjectStructure } from './useProjectStructure';

export const requirementsKeys = makeBootstrapKeys('requirements');

export function useRequirements(projectId: string) {
  return useQuery({
    queryKey: requirementsKeys.detail(projectId),
    queryFn: () => reqsApi.getRequirements(projectId),
    enabled: !!projectId,
    refetchInterval: runningRefetchInterval,
  });
}

/**
 * Top-level ``resp_*`` nodes for the project, derived from the
 * structure snapshot. Top-level resps are resp-tier nodes with
 * ``parent_id === null``; subresps (parented under comps) are
 * intentionally excluded.
 */
export function useResponsibilities(projectId: string) {
  const query = useProjectStructure(projectId);
  const responsibilities = useMemo(() => {
    const nodes = query.data?.nodes ?? [];
    return nodes
      .filter((n) => n.tier === 'resp' && n.parent_id === null)
      .sort((a, b) => a.display_order - b.display_order)
      .map((n) => ({ id: n.id, name: n.name, content: n.content }));
  }, [query.data]);
  return {
    ...query,
    data: query.data ? { responsibilities } : undefined,
  };
}
