import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as projectApi from '../../api/projects';
import { projectKeys } from '../queries/useProjectQueries';
import { pipelineKeys } from '../queries/usePipelineQueries';

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

export function useUpdateArtifact(projectId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['projects', 'updateArtifact'],
    mutationFn: (params: { artifactId: string; content: string; clearAiReview?: boolean }) =>
      projectApi.updateArtifact(params.artifactId, params.content, params.clearAiReview),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: projectKeys.artifact(variables.artifactId) });
      if (projectId) {
        queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
      }
    },
  });
}
