import { useQuery } from '@tanstack/react-query';
import * as structureApi from '../../api/structure';

/**
 * Single source of truth for "what nodes/edges exist in this
 * project and what's their status." Replaces nav-tree,
 * decomposition-graph, responsibility-coverage, and every list
 * endpoint. Stays fresh via SSE-driven invalidation from
 * :func:`useProjectEventStream` — no polling.
 */
export const structureKeys = {
  all: ['structure'] as const,
  project: (projectId: string) => ['structure', projectId] as const,
};

export function useProjectStructure(projectId: string) {
  return useQuery({
    queryKey: structureKeys.project(projectId),
    queryFn: () => structureApi.getProjectStructure(projectId),
    enabled: !!projectId,
    // No refetchInterval — the event stream invalidates this
    // query whenever a relevant event commits. Polling would
    // just duplicate that signal at a 2s lag.
  });
}
