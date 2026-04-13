import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as settingsApi from '../../api/projectSettings';
import type { ProjectSettings } from '../../api/projectSettings';

export const projectSettingsKeys = {
  all: ['projectSettings'] as const,
  detail: (id: string) => [...projectSettingsKeys.all, id] as const,
};

export function useProjectSettings(projectId: string) {
  return useQuery({
    queryKey: projectSettingsKeys.detail(projectId),
    queryFn: () => settingsApi.getProjectSettings(projectId),
    enabled: !!projectId,
  });
}

export function useUpdateProjectSettings(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['projectSettings', 'update', projectId],
    mutationFn: (settings: ProjectSettings) =>
      settingsApi.updateProjectSettings(projectId, settings),
    onSuccess: (data) => {
      queryClient.setQueryData<ProjectSettings>(
        projectSettingsKeys.detail(projectId),
        data
      );
    },
  });
}
