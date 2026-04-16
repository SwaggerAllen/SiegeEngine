import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as refsApi from '../../api/references';
import { referenceKeys } from '../queries/useReferenceQueries';

interface CreateVars {
  name: string;
  seedDescription: string;
  relatedNodes: string[];
}

export function useCreateReferenceMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['references', 'create', projectId],
    mutationFn: (vars: CreateVars) =>
      refsApi.createReference(
        projectId,
        vars.name,
        vars.seedDescription,
        vars.relatedNodes,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: referenceKeys.project(projectId) });
    },
  });
}

interface UpdateVars {
  refId: string;
  feedback: string | null;
}

export function useUpdateReferenceMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['references', 'update', projectId],
    mutationFn: (vars: UpdateVars) =>
      refsApi.updateReference(projectId, vars.refId, vars.feedback),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({
        queryKey: referenceKeys.detail(projectId, vars.refId),
      });
    },
  });
}

interface DraftVars {
  refId: string;
  draftId: string;
}

export function useApproveReferenceMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['references', 'approve', projectId],
    mutationFn: (vars: DraftVars) =>
      refsApi.approveReferenceDraft(projectId, vars.refId, vars.draftId),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: referenceKeys.project(projectId) });
      queryClient.invalidateQueries({
        queryKey: referenceKeys.detail(projectId, vars.refId),
      });
    },
  });
}

export function useDiscardReferenceMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['references', 'discard', projectId],
    mutationFn: (vars: DraftVars) =>
      refsApi.discardReferenceDraft(projectId, vars.refId, vars.draftId),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({
        queryKey: referenceKeys.detail(projectId, vars.refId),
      });
    },
  });
}

export function useDeleteReferenceMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['references', 'delete', projectId],
    mutationFn: (refId: string) => refsApi.deleteReference(projectId, refId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: referenceKeys.project(projectId) });
    },
  });
}

interface EdgeVars {
  sourceId: string;
  targetId: string;
}

export function useAddReferenceEdgeMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['references', 'addEdge', projectId],
    mutationFn: (vars: EdgeVars) =>
      refsApi.addReferenceEdge(projectId, vars.sourceId, vars.targetId),
    onSuccess: (_data, vars) => {
      // Both endpoints may be in the detail view, so invalidate generically
      queryClient.invalidateQueries({ queryKey: referenceKeys.all });
      queryClient.invalidateQueries({
        queryKey: referenceKeys.detail(projectId, vars.sourceId),
      });
      queryClient.invalidateQueries({
        queryKey: referenceKeys.detail(projectId, vars.targetId),
      });
    },
  });
}

export function useRemoveReferenceEdgeMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['references', 'removeEdge', projectId],
    mutationFn: (vars: EdgeVars) =>
      refsApi.removeReferenceEdge(projectId, vars.sourceId, vars.targetId),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: referenceKeys.all });
      queryClient.invalidateQueries({
        queryKey: referenceKeys.detail(projectId, vars.sourceId),
      });
      queryClient.invalidateQueries({
        queryKey: referenceKeys.detail(projectId, vars.targetId),
      });
    },
  });
}
