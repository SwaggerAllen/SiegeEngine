import { useQuery } from '@tanstack/react-query';
import * as subreqsApi from '../../api/subreqs';
import { makeBootstrapKeys } from '../useBootstrapHooks';

export const subreqsKeys = makeBootstrapKeys('subreqs');

export const subresponsibilitiesKeys = {
  all: ['subresponsibilities'] as const,
  list: (projectId: string, compId: string) =>
    [...subresponsibilitiesKeys.all, 'list', projectId, compId] as const,
};

export function useSubreqs(projectId: string, componentId: string) {
  return useQuery({
    queryKey: subreqsKeys.detail(projectId, componentId),
    queryFn: () => subreqsApi.getSubreqs(projectId, componentId),
    enabled: !!projectId && !!componentId,
  });
}

export function useSubresponsibilities(
  projectId: string,
  componentId: string
) {
  return useQuery({
    queryKey: subresponsibilitiesKeys.list(projectId, componentId),
    queryFn: () => subreqsApi.getSubresponsibilities(projectId, componentId),
    enabled: !!projectId && !!componentId,
  });
}
