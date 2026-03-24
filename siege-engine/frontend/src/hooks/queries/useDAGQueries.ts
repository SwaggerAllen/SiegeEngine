import { useQuery } from '@tanstack/react-query';
import * as pipelineApi from '../../api/pipeline';

export const dagKeys = {
  all: (projectId: string) => ['dag', projectId] as const,
  workflow: (projectId: string) => [...dagKeys.all(projectId), 'workflow'] as const,
  documents: (projectId: string) => [...dagKeys.all(projectId), 'documents'] as const,
};

export function useDAGData(projectId: string) {
  return useQuery({
    queryKey: dagKeys.workflow(projectId),
    queryFn: () => pipelineApi.getDAG(projectId),
    enabled: !!projectId,
  });
}

export function useDocumentsDAGData(projectId: string) {
  return useQuery({
    queryKey: dagKeys.documents(projectId),
    queryFn: () => pipelineApi.getDocumentsDAG(projectId),
    enabled: !!projectId,
  });
}
