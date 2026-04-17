import { useQuery } from '@tanstack/react-query';
import * as subreqsApi from '../../api/subreqs';
import { makeBootstrapKeys } from '../useBootstrapHooks';

export const subreqsKeys = makeBootstrapKeys('subreqs');

export function useSubreqs(projectId: string, componentId: string) {
  return useQuery({
    queryKey: subreqsKeys.detail(projectId, componentId),
    queryFn: () => subreqsApi.getSubreqs(projectId, componentId),
    enabled: !!projectId && !!componentId,
  });
}
