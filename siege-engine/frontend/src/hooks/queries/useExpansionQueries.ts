import { useQuery } from '@tanstack/react-query';
import * as expansionApi from '../../api/expansion';

export const expansionKeys = {
  all: ['expansion'] as const,
  detail: (projectId: string) => [...expansionKeys.all, projectId] as const,
};

export function useExpansion(projectId: string) {
  return useQuery({
    queryKey: expansionKeys.detail(projectId),
    queryFn: () => expansionApi.getExpansion(projectId),
    enabled: !!projectId,
    refetchInterval: (query) =>
      query.state.data?.generation_status === 'running' ? 2000 : false,
  });
}
