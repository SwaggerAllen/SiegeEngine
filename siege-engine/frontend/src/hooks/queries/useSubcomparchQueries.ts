import { useQuery } from '@tanstack/react-query';
import * as subcomparchApi from '../../api/subcomparch';
import { makeBootstrapKeys } from '../useBootstrapHooks';

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
    refetchInterval: (query) =>
      query.state.data?.generation_status === 'running' ? 2000 : false,
  });
}
