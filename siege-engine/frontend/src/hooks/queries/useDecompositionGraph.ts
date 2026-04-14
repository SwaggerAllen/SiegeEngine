import { useQuery } from '@tanstack/react-query';
import { getDecompositionGraph } from '../../api/decomposition';

export const decompositionGraphKeys = {
  all: ['decomposition-graph'] as const,
  detail: (projectId: string) => [...decompositionGraphKeys.all, projectId] as const,
};

/**
 * Fetch the full decomposition graph payload for a project.
 * Returns all comp_* + resp_* nodes plus their dependency,
 * decomposition, and domain_parent edges. The Cytoscape
 * component consumes this and filters per view.
 */
export function useDecompositionGraph(projectId: string) {
  return useQuery({
    queryKey: decompositionGraphKeys.detail(projectId),
    queryFn: () => getDecompositionGraph(projectId),
    enabled: !!projectId,
  });
}
