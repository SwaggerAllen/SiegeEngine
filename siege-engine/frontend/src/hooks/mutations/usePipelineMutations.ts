import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as pipelineApi from '../../api/pipeline';
import { pipelineKeys } from '../queries/usePipelineQueries';
import { dagKeys } from '../queries/useDAGQueries';
import type { PipelineStartOptions } from '../../types/pipeline';

export function useStartPipeline(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['pipeline', projectId, 'start'],
    mutationFn: (options?: PipelineStartOptions) =>
      pipelineApi.startPipeline(projectId, options),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pipelineKeys.runs(projectId) });
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
    },
  });
}

export function useResumeRun(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['pipeline', projectId, 'resumeRun'],
    mutationFn: (options?: PipelineStartOptions) =>
      pipelineApi.resumeRun(projectId, options),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pipelineKeys.runs(projectId) });
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
    },
  });
}

export function useResumeStage(projectId: string) {
  return useMutation({
    mutationKey: ['pipeline', projectId, 'resumeStage'],
    mutationFn: (params: {
      executionId: string;
      action: string;
      notes?: string;
      editedContent?: string;
    }) =>
      pipelineApi.resumeStage(
        projectId,
        params.executionId,
        params.action,
        params.notes,
        params.editedContent,
      ),
  });
}

export function useReviseArtifact(projectId: string) {
  return useMutation({
    mutationKey: ['pipeline', projectId, 'reviseArtifact'],
    mutationFn: (params: { artifactId: string; feedback: string }) =>
      pipelineApi.reviseArtifact(projectId, params.artifactId, params.feedback),
  });
}

export function useResolveStale(projectId: string) {
  return useMutation({
    mutationKey: ['pipeline', projectId, 'resolveStale'],
    mutationFn: (params: {
      artifactId: string;
      action: string;
      notes?: string;
      editedContent?: string;
    }) =>
      pipelineApi.resolveStale(
        projectId,
        params.artifactId,
        params.action,
        params.notes,
        params.editedContent,
      ),
  });
}

export function useRegenDownstream(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['pipeline', projectId, 'regenDownstream'],
    mutationFn: (artifactId: string) =>
      pipelineApi.regenDownstream(projectId, artifactId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pipelineKeys.runs(projectId) });
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
    },
  });
}

export function useCancelPipeline(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['pipeline', projectId, 'cancel'],
    mutationFn: (options?: {
      open_pr?: boolean;
      pr_title?: string;
      pr_body?: string;
      base_branch?: string;
    }) => pipelineApi.cancelPipeline(projectId, options),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pipelineKeys.runs(projectId) });
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
      queryClient.invalidateQueries({ queryKey: pipelineKeys.blockingPR(projectId) });
    },
  });
}

export function useResetAll(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['pipeline', projectId, 'resetAll'],
    mutationFn: () => pipelineApi.resetAll(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pipelineKeys.runs(projectId) });
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
    },
  });
}

export function useCheckBlockingPR(projectId: string) {
  return useMutation({
    mutationKey: ['pipeline', projectId, 'checkBlockingPR'],
    mutationFn: () => pipelineApi.checkBlockingPR(projectId),
  });
}

export function useDismissBlockingPR(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['pipeline', projectId, 'dismissBlockingPR'],
    mutationFn: () => pipelineApi.dismissBlockingPR(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pipelineKeys.blockingPR(projectId) });
    },
  });
}

export function useConsolidateArtifact(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['pipeline', projectId, 'consolidateArtifact'],
    mutationFn: (artifactId: string) =>
      pipelineApi.consolidateArtifact(projectId, artifactId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
    },
  });
}

export function useCancelStage(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['pipeline', projectId, 'cancelStage'],
    mutationFn: (executionId: string) =>
      pipelineApi.cancelStage(projectId, executionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
    },
  });
}

export function useRetryStage(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['pipeline', projectId, 'retryStage'],
    mutationFn: (executionId: string) =>
      pipelineApi.retryStage(projectId, executionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
    },
  });
}

export function useForceRestartStage(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['pipeline', projectId, 'forceRestartStage'],
    mutationFn: (executionId: string) =>
      pipelineApi.forceRestartStage(projectId, executionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
    },
  });
}

export function useTriggerStage(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['pipeline', projectId, 'triggerStage'],
    mutationFn: (params: { stageKey: string; componentKey?: string | null }) =>
      pipelineApi.triggerStage(projectId, params.stageKey, params.componentKey),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
    },
  });
}

export function usePruneArtifact(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['pipeline', projectId, 'pruneArtifact'],
    mutationFn: (artifactId: string) =>
      pipelineApi.pruneArtifact(projectId, artifactId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
    },
  });
}

export function usePruneDescendants(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ['pipeline', projectId, 'pruneDescendants'],
    mutationFn: (stageKey: string) =>
      pipelineApi.pruneDescendants(projectId, stageKey),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
      queryClient.invalidateQueries({ queryKey: dagKeys.all(projectId) });
    },
  });
}
