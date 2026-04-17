import { useQuery } from '@tanstack/react-query';
import * as faninApi from '../../api/fanin';
import { runningRefetchInterval } from '../useBootstrapHooks';

/**
 * Phase 7 fan-in inspection query. Scoped by ``(projectId, compId)``
 * where ``compId`` is the owning domain comp. Only fanned-out
 * domain comps have a fan-in child; a 404 here means the comp
 * is presentational or un-fanned-out.
 *
 * Polls every 2 seconds while a regen is in flight so the status
 * + telemetry refresh without a manual reload, mirroring the
 * impl / comparch / subcomparch query pattern.
 */
export const faninKeys = {
  all: ['fanin'] as const,
  project: (projectId: string) => ['fanin', projectId] as const,
  detail: (projectId: string, compId: string) =>
    ['fanin', projectId, compId] as const,
};

export function useFanIn(projectId: string, compId: string) {
  return useQuery({
    queryKey: faninKeys.detail(projectId, compId),
    queryFn: () => faninApi.getFanIn(projectId, compId),
    enabled: !!projectId && !!compId,
    // A 404 here is a deliberate signal "comp has no fan-in
    // child" (presentational or un-fanned-out). Retrying on that
    // is pointless noise — it floods the error log every time a
    // comparch page mounts for a comp without a fan-in.
    retry: false,
    refetchInterval: runningRefetchInterval,
  });
}
