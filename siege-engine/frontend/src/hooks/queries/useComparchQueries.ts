import { useQuery } from '@tanstack/react-query';
import * as comparchApi from '../../api/comparch';
import { makeBootstrapKeys } from '../useBootstrapHooks';

export const comparchKeys = makeBootstrapKeys('comparch');

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

export function useComparch(projectId: string, componentId: string) {
  return useQuery({
    queryKey: comparchKeys.detail(projectId, componentId),
    queryFn: () => comparchApi.getComparch(projectId, componentId),
    enabled: !!projectId && !!componentId,
  });
}

export function useSubcomponents(
  projectId: string,
  componentId: string
) {
  return useQuery({
    queryKey: subcomponentsKeys.list(projectId, componentId),
    queryFn: () => comparchApi.getSubcomponents(projectId, componentId),
    enabled: !!projectId && !!componentId,
  });
}

export function useComponentLocalPolicies(
  projectId: string,
  componentId: string
) {
  return useQuery({
    queryKey: componentLocalPoliciesKeys.list(projectId, componentId),
    queryFn: () => comparchApi.getComponentLocalPolicies(projectId, componentId),
    enabled: !!projectId && !!componentId,
  });
}

export function useAppliedPolicies(projectId: string, componentId: string) {
  return useQuery({
    queryKey: appliedPoliciesKeys.list(projectId, componentId),
    queryFn: () => comparchApi.getAppliedPolicies(projectId, componentId),
    enabled: !!projectId && !!componentId,
  });
}
