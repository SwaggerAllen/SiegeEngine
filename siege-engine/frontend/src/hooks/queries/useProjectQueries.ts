import { useQuery } from '@tanstack/react-query';
import * as projectApi from '../../api/projects';

export const projectKeys = {
  all: ['projects'] as const,
  lists: () => [...projectKeys.all, 'list'] as const,
  detail: (id: string) => [...projectKeys.all, 'detail', id] as const,
  artifact: (id: string) => [...projectKeys.all, 'artifact', id] as const,
};

export function useProjects() {
  return useQuery({
    queryKey: projectKeys.lists(),
    queryFn: () => projectApi.listProjects(),
  });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: projectKeys.detail(id),
    queryFn: () => projectApi.getProject(id),
    enabled: !!id,
  });
}

export function useArtifact(id: string | null) {
  return useQuery({
    queryKey: projectKeys.artifact(id!),
    queryFn: () => projectApi.getArtifact(id!),
    enabled: !!id,
  });
}
