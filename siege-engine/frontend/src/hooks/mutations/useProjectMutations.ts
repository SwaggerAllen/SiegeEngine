import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as projectApi from '../../api/projects';
import { projectKeys } from '../queries/useProjectQueries';

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['projects', 'create'],
    mutationFn: (params: { name: string; description: string | null; content: string }) =>
      projectApi.createProject(params.name, params.description, params.content),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
}

export function useDeleteProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['projects', 'delete'],
    mutationFn: (id: string) => projectApi.deleteProject(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
}

export function useCloneProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['projects', 'clone'],
    mutationFn: (params: { id: string; newName?: string }) =>
      projectApi.cloneProject(params.id, params.newName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
}
