import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import * as sysarchApi from '../../api/sysarch';
import { makeBootstrapKeys, runningRefetchInterval } from '../useBootstrapHooks';
import { useProjectStructure } from './useProjectStructure';

export const sysarchKeys = makeBootstrapKeys('sysarch');

export function useSysarch(projectId: string) {
  return useQuery({
    queryKey: sysarchKeys.detail(projectId),
    queryFn: () => sysarchApi.getSysarch(projectId),
    enabled: !!projectId,
    refetchInterval: runningRefetchInterval,
  });
}

/**
 * Top-level ``comp_*`` nodes for the project, derived from the
 * structure snapshot. Used by ``SysarchPanel`` to annotate
 * component cards with the pending-draft amber border when a
 * comp has a draft waiting for review. The returned
 * ``pending_draft_kind`` is a truthy sentinel rather than the
 * specific tier name — the renderer only checks for truthiness.
 */
export function useComponents(projectId: string) {
  const query = useProjectStructure(projectId);
  const components = useMemo(() => {
    const nodes = query.data?.nodes ?? [];
    return nodes
      .filter((n) => n.tier === 'comp' && n.parent_id === null)
      .sort((a, b) => a.display_order - b.display_order)
      .map((n) => ({
        id: n.id,
        name: n.name,
        kind: n.kind,
        pending_draft_kind: n.has_pending_draft ? 'pending' : null,
      }));
  }, [query.data]);
  return {
    ...query,
    data: query.data ? { components } : undefined,
  };
}
