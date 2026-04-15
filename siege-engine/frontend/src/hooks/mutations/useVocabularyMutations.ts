import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as vocabApi from '../../api/vocabulary';
import { vocabularyKeys } from '../queries/useVocabularyQueries';

interface CreateVars {
  name: string;
  content: string;
  parentId: string | null;
}

export function useCreateVocabMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['vocabulary', 'create', projectId],
    mutationFn: (vars: CreateVars) =>
      vocabApi.createVocabEntry(
        projectId,
        vars.name,
        vars.content,
        vars.parentId
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: vocabularyKeys.project(projectId),
      });
    },
  });
}

interface EditVars {
  vocabId: string;
  newContent: string;
}

export function useEditVocabMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['vocabulary', 'edit', projectId],
    mutationFn: (vars: EditVars) =>
      vocabApi.editVocabEntry(projectId, vars.vocabId, vars.newContent),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({
        queryKey: vocabularyKeys.project(projectId),
      });
      queryClient.invalidateQueries({
        queryKey: vocabularyKeys.entry(projectId, vars.vocabId),
      });
    },
  });
}

interface RenameVars {
  vocabId: string;
  newName: string;
}

export function useRenameVocabMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['vocabulary', 'rename', projectId],
    mutationFn: (vars: RenameVars) =>
      vocabApi.renameVocabEntry(projectId, vars.vocabId, vars.newName),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: vocabularyKeys.project(projectId),
      });
    },
  });
}

interface ReparentVars {
  vocabId: string;
  newParentId: string | null;
}

export function useReparentVocabMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['vocabulary', 'reparent', projectId],
    mutationFn: (vars: ReparentVars) =>
      vocabApi.reparentVocabEntry(
        projectId,
        vars.vocabId,
        vars.newParentId
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: vocabularyKeys.project(projectId),
      });
    },
  });
}

export function useDeleteVocabMutation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['vocabulary', 'delete', projectId],
    mutationFn: (vocabId: string) =>
      vocabApi.deleteVocabEntry(projectId, vocabId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: vocabularyKeys.project(projectId),
      });
    },
  });
}
