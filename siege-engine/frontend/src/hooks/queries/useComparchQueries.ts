import { useQuery } from '@tanstack/react-query';
import * as comparchApi from '../../api/comparch';
import { makeBootstrapKeys, runningRefetchInterval } from '../useBootstrapHooks';

export const comparchKeys = makeBootstrapKeys('comparch');

export function useComparch(projectId: string, componentId: string) {
  return useQuery({
    queryKey: comparchKeys.detail(projectId, componentId),
    queryFn: () => comparchApi.getComparch(projectId, componentId),
    enabled: !!projectId && !!componentId,
    refetchInterval: runningRefetchInterval,
  });
}
