import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import * as siegeApi from '../../api/siege';
import * as structureApi from '../../api/structure';
import { v3ToLegacyStructure } from '../../lib/v3ToLegacyStructure';
import { useProject } from './useProjectQueries';

/**
 * Source-aware structure feed for the read-only viz components
 * (FullDagView today; nav tree / overview to follow).
 *
 * Branches on ``project.source``:
 * - ``"remote"`` → the legacy ``/api/projects/:id/structure`` read,
 *   same query key + cache as ``useProjectStructure``.
 * - ``"upload"`` → the v3 ``/siege/api/get-project-graph`` read,
 *   adapted to the legacy ``StructureResponse`` shape so the consumers
 *   don't have to branch.
 *
 * Both useQuery calls are declared unconditionally (hooks-rules) but
 * only one is ``enabled`` at a time based on the project's source.
 * Returns the same ``{data, isLoading, error}`` shape the legacy hook
 * exposes.
 */
export function useStructureForViz(projectId: string) {
  const { data: project } = useProject(projectId);
  const hasProject = !!project;
  const isUpload = project?.source === 'upload';

  const legacy = useQuery({
    queryKey: ['structure', projectId],
    queryFn: () => structureApi.getProjectStructure(projectId),
    enabled: hasProject && !isUpload,
  });

  const v3 = useQuery({
    queryKey: ['v3-graph', projectId, 'main'],
    queryFn: () => siegeApi.getProjectGraph(projectId, 'main'),
    enabled: hasProject && isUpload,
  });

  const v3Adapted = useMemo(
    () => (v3.data ? v3ToLegacyStructure(v3.data) : undefined),
    [v3.data],
  );

  if (isUpload) {
    return { data: v3Adapted, isLoading: v3.isLoading, error: v3.error };
  }
  return { data: legacy.data, isLoading: legacy.isLoading, error: legacy.error };
}
