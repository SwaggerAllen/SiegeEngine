import { useQuery } from '@tanstack/react-query';
import * as pipelineApi from '../../api/pipeline';

export const dagKeys = {
  all: (projectId: string) => ['dag', projectId] as const,
  workflow: (projectId: string) => [...dagKeys.all(projectId), 'workflow'] as const,
  documents: (projectId: string, dagType: string = 'domain') =>
    [...dagKeys.all(projectId), 'documents', dagType] as const,
  components: (projectId: string, parentKey?: string | null) =>
    [...dagKeys.all(projectId), 'components', parentKey ?? null] as const,
  crossDagStatus: (projectId: string) =>
    [...dagKeys.all(projectId), 'cross-dag-status'] as const,
};

export function useDAGData(projectId: string) {
  return useQuery({
    queryKey: dagKeys.workflow(projectId),
    queryFn: () => pipelineApi.getDAG(projectId),
    enabled: !!projectId,
  });
}

export function useDocumentsDAGData(projectId: string, dagType: string = 'domain') {
  return useQuery({
    queryKey: dagKeys.documents(projectId, dagType),
    queryFn: () => pipelineApi.getDocumentsDAG(projectId, dagType),
    enabled: !!projectId,
  });
}

export function useComponents(projectId: string, parentKey?: string | null) {
  return useQuery({
    queryKey: dagKeys.components(projectId, parentKey),
    queryFn: () => pipelineApi.getComponents(projectId, parentKey),
    enabled: !!projectId,
  });
}

export function useCrossDagStatus(projectId: string) {
  return useQuery({
    queryKey: dagKeys.crossDagStatus(projectId),
    queryFn: () => pipelineApi.getCrossDagStatus(projectId),
    enabled: !!projectId,
  });
}
