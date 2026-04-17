import { useQuery } from '@tanstack/react-query';
import * as navTreeApi from '../../api/navTree';

/**
 * Fetches the flat list of sidebar tree nodes for a project.
 *
 * Polls every 2 seconds whenever any node has an active
 * generation running, so the pulse badges flip off cleanly when
 * the job completes. Idles when nothing is generating.
 */
export const navTreeKeys = {
  all: ['nav-tree'] as const,
  project: (projectId: string) => ['nav-tree', projectId] as const,
};

export function useNavTree(projectId: string) {
  return useQuery({
    queryKey: navTreeKeys.project(projectId),
    queryFn: () => navTreeApi.getNavTree(projectId),
    enabled: !!projectId,
    refetchInterval: (query) => {
      const running = query.state.data?.nodes.some((n) => n.generation_running);
      return running ? 2000 : false;
    },
  });
}
