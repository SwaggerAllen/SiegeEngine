import { useQuery } from '@tanstack/react-query';
import * as reqsApi from '../../api/requirements';
import { makeBootstrapKeys } from '../useBootstrapHooks';

export const requirementsKeys = makeBootstrapKeys('requirements');

export const responsibilitiesKeys = {
  all: ['responsibilities'] as const,
  list: (projectId: string) => [...responsibilitiesKeys.all, 'list', projectId] as const,
};

export function useRequirements(projectId: string) {
  return useQuery({
    queryKey: requirementsKeys.detail(projectId),
    queryFn: () => reqsApi.getRequirements(projectId),
    enabled: !!projectId,
  });
}

export function useResponsibilities(projectId: string) {
  return useQuery({
    queryKey: responsibilitiesKeys.list(projectId),
    queryFn: () => reqsApi.getResponsibilities(projectId),
    enabled: !!projectId,
  });
}
