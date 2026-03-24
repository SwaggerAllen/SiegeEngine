import { useEffect } from 'react';
import { useProject } from './queries/useProjectQueries';
import { usePipelineConfig, usePipelineStatus, usePipelineRuns, useBlockingPR } from './queries/usePipelineQueries';
import { useDAGData, useDocumentsDAGData } from './queries/useDAGQueries';
import { useProjectStore } from '../store/projectStore';
import { usePipelineUIStore } from '../store/pipelineUIStore';

/**
 * Centralized initialization for the project dashboard.
 *
 * Uses TanStack Query for data fetching (parallel, cached, auto-retry).
 * Gates child rendering via the `ready` flag.
 */
export function useProjectInit(projectId: string): { ready: boolean; error: Error | null } {
  // --- TQ queries (all fire in parallel automatically) ---
  const project = useProject(projectId);
  usePipelineConfig(projectId);
  usePipelineStatus(projectId);
  usePipelineRuns(projectId);
  useBlockingPR(projectId);
  useDAGData(projectId);
  useDocumentsDAGData(projectId);

  // --- Reset stale data on project change ---
  useEffect(() => {
    usePipelineUIStore.getState().reset();
    return () => {
      useProjectStore.getState().clearSelection();
    };
  }, [projectId]);

  // --- Bridge: sync project data to Zustand for selectedArtifact/currentProject consumers ---
  useEffect(() => {
    if (project.data) {
      useProjectStore.setState({ currentProject: project.data, loading: false });
    }
  }, [project.data]);

  // --- Gate rendering on critical data ---
  const ready = project.isSuccess;
  const error = project.error instanceof Error
    ? project.error
    : project.error
      ? new Error('Failed to load project')
      : null;

  return { ready, error };
}
