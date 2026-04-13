import { useQuery } from '@tanstack/react-query';
import * as featuresApi from '../../api/features';

export const featureKeys = {
  all: ['features'] as const,
  list: (projectId: string) => [...featureKeys.all, 'list', projectId] as const,
};

/**
 * Fetch the project's `feat_*` nodes.
 *
 * The ``mintPending`` argument tells the hook to poll the endpoint
 * while the feature list might be in the process of populating —
 * i.e. the expansion has been approved but the mint handler
 * hasn't run yet. When the list is non-empty or when mintPending
 * becomes false, the poll stops.
 *
 * In practice the caller passes ``mintPending`` as a boolean
 * derived from the expansion query: "has the user approved the
 * expansion but the feature list is still empty?"
 */
export function useFeatures(projectId: string, mintPending: boolean = false) {
  return useQuery({
    queryKey: featureKeys.list(projectId),
    queryFn: () => featuresApi.getFeatures(projectId),
    enabled: !!projectId,
    refetchInterval: (query) => {
      // Poll while the mint handler might still be running. Stop
      // as soon as we see features or the caller says the mint is
      // no longer pending.
      if (!mintPending) return false;
      const hasFeatures = (query.state.data?.features.length ?? 0) > 0;
      return hasFeatures ? false : 2000;
    },
  });
}
