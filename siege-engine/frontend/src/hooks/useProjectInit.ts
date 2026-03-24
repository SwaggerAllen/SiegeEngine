import { useEffect } from 'react';
import { useProject } from './queries/useProjectQueries';
import { usePipelineConfig, usePipelineStatus, usePipelineRuns, useBlockingPR } from './queries/usePipelineQueries';
import { useDAGData, useDocumentsDAGData } from './queries/useDAGQueries';
import { useProjectStore } from '../store/projectStore';
import { usePipelineStore } from '../store/pipelineStore';
import { useDAGStore } from '../store/dagStore';
import { usePipelineUIStore } from '../store/pipelineUIStore';
import type { PipelineRun } from '../types/pipeline';

/**
 * Centralized initialization for the project dashboard.
 *
 * Uses TanStack Query for data fetching (parallel, cached, auto-retry).
 * Bridges data back to Zustand stores so non-migrated components still work.
 * Gates child rendering via the `ready` flag.
 */
export function useProjectInit(projectId: string): { ready: boolean; error: Error | null } {
  // --- TQ queries (all fire in parallel automatically) ---
  const project = useProject(projectId);
  const config = usePipelineConfig(projectId);
  const status = usePipelineStatus(projectId);
  const runs = usePipelineRuns(projectId);
  const blockingPR = useBlockingPR(projectId);
  const dag = useDAGData(projectId);
  const docsDag = useDocumentsDAGData(projectId);

  // --- Reset stale data on project change ---
  useEffect(() => {
    usePipelineStore.getState().reset();
    usePipelineUIStore.getState().reset();
    return () => {
      useProjectStore.getState().clearSelection();
    };
  }, [projectId]);

  // --- Bridge: sync TQ data → Zustand stores for non-migrated consumers ---

  // Project store
  useEffect(() => {
    if (project.data) {
      useProjectStore.setState({ currentProject: project.data, loading: false });
    }
  }, [project.data]);

  // Pipeline config
  useEffect(() => {
    if (config.data) {
      usePipelineStore.setState({ config: config.data });
    }
  }, [config.data]);

  // Pipeline status (executions + snapshot + derived state)
  useEffect(() => {
    if (status.data) {
      const snapshot = status.data.snapshot;
      usePipelineStore.setState({
        executions: status.data.stages,
        snapshot,
        isRunning: snapshot.is_running,
        isPaused: snapshot.is_paused,
        pausedStage: snapshot.paused_stage,
      });
    }
  }, [status.data]);

  // Pipeline runs
  useEffect(() => {
    if (runs.data) {
      const activeRun = runs.data.find((r: PipelineRun) => r.status === 'running' || r.status === 'paused');
      usePipelineStore.setState({
        runs: runs.data,
        currentRunNumber: activeRun?.run_number ?? (runs.data.length > 0 ? runs.data[0].run_number : null),
      });
    }
  }, [runs.data]);

  // Blocking PR
  useEffect(() => {
    if (blockingPR.data) {
      usePipelineStore.setState({
        blockingPR: blockingPR.data.blocking_pr_url
          ? { url: blockingPR.data.blocking_pr_url, number: blockingPR.data.blocking_pr_number! }
          : null,
      });
    }
  }, [blockingPR.data]);

  // DAG store bridge — use the store's own mapping/equality logic
  useEffect(() => {
    if (dag.data) {
      // Call fetchDAG which handles node/edge mapping and equality checks
      useDAGStore.getState().fetchDAG(projectId);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dag.data]);

  useEffect(() => {
    if (docsDag.data) {
      useDAGStore.getState().fetchDocumentsDAG(projectId);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docsDag.data]);

  // --- Gate rendering on critical data ---
  const ready = project.isSuccess;
  const error = project.error instanceof Error
    ? project.error
    : project.error
      ? new Error('Failed to load project')
      : null;

  return { ready, error };
}
