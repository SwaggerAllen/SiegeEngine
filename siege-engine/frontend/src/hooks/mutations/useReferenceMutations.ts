import { useMutation, useQueryClient } from '@tanstack/react-query';
import { makeReferencesApi } from '../../api/references';
import { makeBootstrapKeys, makeBootstrapMutations } from '../useBootstrapHooks';
import { referenceKeys } from '../queries/useReferenceQueries';

// The standard bootstrap mutations (feedback / approve / discard
// / cancel) are produced by makeBootstrapMutations against a
// per-project ref API. Ref-specific mutations (create / delete /
// add-edge / remove-edge) live below.

const referenceBootstrapKeys = makeBootstrapKeys('references');

function makeApiFns(projectId: string) {
  const apiInst = makeReferencesApi(projectId);
  // Cast through `unknown` so the bootstrap helpers' looser
  // `(...string[])` shape lines up with the API's stricter
  // variadic types — the helpers just thread the args through.
  return {
    postFeedback: apiInst.postFeedback as unknown as (
      ...args: Array<string | number>
    ) => Promise<{ job_id: string }>,
    approveDraft: apiInst.approveDraft as unknown as (
      ...args: string[]
    ) => Promise<unknown>,
    discardDraft: apiInst.discardDraft as unknown as (
      ...args: string[]
    ) => Promise<unknown>,
    cancelGeneration: apiInst.cancelGeneration as unknown as (
      ...args: string[]
    ) => Promise<unknown>,
  };
}

function bootstrapMutationsFor(projectId: string) {
  return makeBootstrapMutations(
    'references',
    makeApiFns(projectId),
    referenceBootstrapKeys,
    (queryClient) => {
      // Any lifecycle change (approve / discard / cancel /
      // feedback) can also affect the project-level list — e.g.
      // the has_content flag flips on approval — so invalidate
      // the list query alongside the detail query.
      queryClient.invalidateQueries({ queryKey: referenceKeys.project(projectId) });
    },
  );
}

export function useUpdateReferenceMutation(projectId: string, refId: string) {
  return bootstrapMutationsFor(projectId).useFeedbackMutation(refId);
}

export function useApproveReferenceMutation(projectId: string, refId: string) {
  return bootstrapMutationsFor(projectId).useApproveMutation(refId);
}

export function useDiscardReferenceMutation(projectId: string, refId: string) {
  return bootstrapMutationsFor(projectId).useDiscardMutation(refId);
}

export function useCancelReferenceMutation(projectId: string, refId: string) {
  return bootstrapMutationsFor(projectId).useCancelGenerationMutation(refId);
}

// ── Ref-specific mutations ───────────────────────────────────────

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
      makeReferencesApi(projectId).create(
        vars.name,
        vars.seedDescription,
        vars.relatedNodes,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: referenceKeys.project(projectId) });
    },
  });
}

export function useDeleteReferenceMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['references', 'delete', projectId],
    mutationFn: (refId: string) => makeReferencesApi(projectId).delete(refId),
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
      makeReferencesApi(projectId).addEdge(vars.sourceId, vars.targetId),
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

export function useRemoveReferenceEdgeMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['references', 'removeEdge', projectId],
    mutationFn: (vars: EdgeVars) =>
      makeReferencesApi(projectId).removeEdge(vars.sourceId, vars.targetId),
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
