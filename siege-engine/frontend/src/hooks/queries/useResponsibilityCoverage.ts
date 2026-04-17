import { useQuery } from '@tanstack/react-query';
import * as api from '../../api/responsibilityCoverage';

/**
 * Fetches the received + computed responsibility lists for a
 * component. Used by the subreqs detail pane to show what was
 * routed to the component vs what the component broke its
 * responsibilities into.
 */
export const responsibilityCoverageKeys = {
  all: ['responsibility-coverage'] as const,
  detail: (projectId: string, compId: string) =>
    ['responsibility-coverage', projectId, compId] as const,
};

export function useResponsibilityCoverage(projectId: string, compId: string) {
  return useQuery({
    queryKey: responsibilityCoverageKeys.detail(projectId, compId),
    queryFn: () => api.getResponsibilityCoverage(projectId, compId),
    enabled: !!projectId && !!compId,
  });
}
