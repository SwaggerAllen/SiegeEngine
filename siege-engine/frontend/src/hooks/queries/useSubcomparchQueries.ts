import { useQuery } from '@tanstack/react-query';
import * as subcomparchApi from '../../api/subcomparch';
import { makeBootstrapKeys, runningRefetchInterval } from '../useBootstrapHooks';

export const subcomparchKeys = makeBootstrapKeys('subcomparch');

export function useSubcomparch(
  projectId: string,
  parentCompId: string,
  subId: string
) {
  return useQuery({
    queryKey: subcomparchKeys.detail(projectId, parentCompId, subId),
    queryFn: () => subcomparchApi.getSubcomparch(projectId, parentCompId, subId),
    enabled: !!projectId && !!parentCompId && !!subId,
    refetchInterval: runningRefetchInterval,
  });
}
