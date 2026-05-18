import { useQuery } from '@tanstack/react-query';
import * as structureApi from '../../api/structure';

/**
 * Single source of truth for "what nodes/edges exist in this
 * project and what's their status." Replaces nav-tree,
 * decomposition-graph, responsibility-coverage, and every list
 * endpoint.
 *
 * Phase 3 migration: SSE invalidation is gone. The dashboard is a
 * single-shot reader against the future MCP HTTP transport; user-
 * initiated refresh (or another query firing a manual invalidation)
 * is the only refetch trigger.
 *
 * FUTURE: MCP server endpoint /api/projects/:id/refs/:ref/structure;
 * see docs/migration/mcp-surface.md
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
