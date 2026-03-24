import { useQuery } from '@tanstack/react-query';
import * as pipelineApi from '../../api/pipeline';
import type { PipelineConfig, PipelineRun, PipelineSnapshot } from '../../types/pipeline';
import type { StageExecution } from '../../schemas/pipeline';

export const pipelineKeys = {
  all: (projectId: string) => ['pipeline', projectId] as const,
  config: (projectId: string) => [...pipelineKeys.all(projectId), 'config'] as const,
  status: (projectId: string) => [...pipelineKeys.all(projectId), 'status'] as const,
  runs: (projectId: string) => [...pipelineKeys.all(projectId), 'runs'] as const,
  blockingPR: (projectId: string) => [...pipelineKeys.all(projectId), 'blockingPR'] as const,
  runState: (projectId: string, runNumber: number) =>
    [...pipelineKeys.all(projectId), 'runState', runNumber] as const,
};

export function usePipelineConfig(projectId: string) {
  return useQuery({
    queryKey: pipelineKeys.config(projectId),
    queryFn: () => pipelineApi.getPipelineConfig(projectId),
    enabled: !!projectId,
  });
}

export interface PipelineStatusResponse {
  stages: StageExecution[];
  snapshot: PipelineSnapshot;
}

export function usePipelineStatus(projectId: string) {
  return useQuery<PipelineStatusResponse>({
    queryKey: pipelineKeys.status(projectId),
    queryFn: () => pipelineApi.getPipelineStatus(projectId),
    enabled: !!projectId,
  });
}

export function usePipelineRuns(projectId: string) {
  return useQuery<PipelineRun[]>({
    queryKey: pipelineKeys.runs(projectId),
    queryFn: () => pipelineApi.listRuns(projectId),
    enabled: !!projectId,
  });
}

export function useBlockingPR(projectId: string) {
  return useQuery({
    queryKey: pipelineKeys.blockingPR(projectId),
    queryFn: () => pipelineApi.getBlockingPR(projectId),
    enabled: !!projectId,
  });
}

export function useRunState(projectId: string, runNumber: number | null) {
  return useQuery({
    queryKey: pipelineKeys.runState(projectId, runNumber!),
    queryFn: () => pipelineApi.getRunState(projectId, runNumber!),
    enabled: !!projectId && runNumber !== null,
  });
}

// --- Derived selectors from query data ---

export function usePipelineSnapshot(projectId: string): PipelineSnapshot | undefined {
  const { data } = usePipelineStatus(projectId);
  return data?.snapshot;
}

export function useIsRunning(projectId: string): boolean {
  const snapshot = usePipelineSnapshot(projectId);
  return snapshot?.is_running ?? false;
}

export function useIsPaused(projectId: string): boolean {
  const snapshot = usePipelineSnapshot(projectId);
  return snapshot?.is_paused ?? false;
}

export function usePausedStage(projectId: string): string | null {
  const snapshot = usePipelineSnapshot(projectId);
  return snapshot?.paused_stage ?? null;
}

export function useExecutions(projectId: string): StageExecution[] {
  const { data } = usePipelineStatus(projectId);
  return data?.stages ?? [];
}

export function usePipelineConfigData(projectId: string): PipelineConfig | null {
  const { data } = usePipelineConfig(projectId);
  return data ?? null;
}

export function useCurrentRunNumber(projectId: string): number | null {
  const { data: runs } = usePipelineRuns(projectId);
  if (!runs || runs.length === 0) return null;
  const activeRun = runs.find((r) => r.status === 'running' || r.status === 'paused');
  return activeRun?.run_number ?? runs[0].run_number;
}
