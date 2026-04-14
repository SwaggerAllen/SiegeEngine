import { useQuery } from '@tanstack/react-query';
import * as comparchApi from '../../api/comparch';

export const comparchKeys = {
  all: ['comparch'] as const,
  detail: (projectId: string, compId: string) =>
    [...comparchKeys.all, projectId, compId] as const,
};

export const subcomponentsKeys = {
  all: ['subcomponents'] as const,
  list: (projectId: string, compId: string) =>
    [...subcomponentsKeys.all, 'list', projectId, compId] as const,
};

export const componentLocalPoliciesKeys = {
  all: ['component-local-policies'] as const,
  list: (projectId: string, compId: string) =>
    [...componentLocalPoliciesKeys.all, 'list', projectId, compId] as const,
};

export const appliedPoliciesKeys = {
  all: ['applied-policies'] as const,
  list: (projectId: string, compId: string) =>
    [...appliedPoliciesKeys.all, 'list', projectId, compId] as const,
};

/**
 * Fetch a single component's comparch draft state — four-state
 * panel reads through this. Polls every 2s while generation is
 * running.
 */
export function useComparch(projectId: string, componentId: string) {
  return useQuery({
    queryKey: comparchKeys.detail(projectId, componentId),
    queryFn: () => comparchApi.getComparch(projectId, componentId),
    enabled: !!projectId && !!componentId,
    refetchInterval: (query) =>
      query.state.data?.generation_status === 'running' ? 2000 : false,
  });
}

/**
 * Fetch the subcomponents minted under a component. Polls every
 * 2s while mintPending is true and the list is still empty.
 */
export function useSubcomponents(
  projectId: string,
  componentId: string,
  mintPending: boolean = false
) {
  return useQuery({
    queryKey: subcomponentsKeys.list(projectId, componentId),
    queryFn: () => comparchApi.getSubcomponents(projectId, componentId),
    enabled: !!projectId && !!componentId,
    refetchInterval: (query) => {
      if (!mintPending) return false;
      const count = query.state.data?.subcomponents.length ?? 0;
      return count > 0 ? false : 2000;
    },
  });
}

/** Fetch component-local policies minted under a component. */
export function useComponentLocalPolicies(
  projectId: string,
  componentId: string,
  mintPending: boolean = false
) {
  return useQuery({
    queryKey: componentLocalPoliciesKeys.list(projectId, componentId),
    queryFn: () => comparchApi.getComponentLocalPolicies(projectId, componentId),
    enabled: !!projectId && !!componentId,
    refetchInterval: (query) => {
      if (!mintPending) return false;
      const count = query.state.data?.policies.length ?? 0;
      return count > 0 ? false : 2000;
    },
  });
}

/**
 * Fetch policies already applied to a component (via
 * policy_application edges). Includes both top-level and
 * component-local applications once the stage 5/6 handlers have
 * run.
 */
export function useAppliedPolicies(projectId: string, componentId: string) {
  return useQuery({
    queryKey: appliedPoliciesKeys.list(projectId, componentId),
    queryFn: () => comparchApi.getAppliedPolicies(projectId, componentId),
    enabled: !!projectId && !!componentId,
  });
}
