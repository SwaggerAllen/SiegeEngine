import { useQuery } from '@tanstack/react-query';
import * as siegeApi from '../../api/siege';

export const projectGraphKeys = {
  all: ['v3-graph'] as const,
  project: (projectId: string, ref: string) =>
    ['v3-graph', projectId, ref] as const,
};

export function useProjectGraph(projectId: string, ref = 'main') {
  return useQuery({
    queryKey: projectGraphKeys.project(projectId, ref),
    queryFn: () => siegeApi.getProjectGraph(projectId, ref),
    enabled: !!projectId,
  });
}
