import { useQuery } from '@tanstack/react-query';
import * as vocabApi from '../../api/vocabulary';

export const vocabularyKeys = {
  all: ['vocabulary'] as const,
  project: (projectId: string) =>
    [...vocabularyKeys.all, 'project', projectId] as const,
  feature: (projectId: string, featId: string) =>
    [...vocabularyKeys.all, 'feature', projectId, featId] as const,
  entry: (projectId: string, vocabId: string) =>
    [...vocabularyKeys.all, 'entry', projectId, vocabId] as const,
};

/**
 * Fetch every vocab entry in a project (project-level + feature-local).
 *
 * The list endpoint returns a flat array with scope metadata on
 * each entry; the caller filters by `parent_id` to separate
 * project-level from feature-local.
 */
export function useProjectVocabulary(projectId: string) {
  return useQuery({
    queryKey: vocabularyKeys.project(projectId),
    queryFn: () => vocabApi.getVocabulary(projectId),
    enabled: !!projectId,
  });
}

/**
 * Fetch vocab entries scoped to one specific feature.
 */
export function useFeatureVocabulary(projectId: string, featId: string) {
  return useQuery({
    queryKey: vocabularyKeys.feature(projectId, featId),
    queryFn: () => vocabApi.getFeatureVocabulary(projectId, featId),
    enabled: !!projectId && !!featId,
  });
}

/**
 * Fetch one vocab entry's full content.
 */
export function useVocabularyEntry(projectId: string, vocabId: string) {
  return useQuery({
    queryKey: vocabularyKeys.entry(projectId, vocabId),
    queryFn: () => vocabApi.getVocabularyEntry(projectId, vocabId),
    enabled: !!projectId && !!vocabId,
  });
}
