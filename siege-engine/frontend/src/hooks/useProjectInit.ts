import { useEffect } from 'react';
import { useProject } from './queries/useProjectQueries';
import { usePipelineConfig, usePipelineStatus, usePipelineRuns, useBlockingPR } from './queries/usePipelineQueries';
import { useDAGData, useDocumentsDAGData } from './queries/useDAGQueries';
import { useProjectStore } from '../store/projectStore';
import { usePipelineUIStore } from '../store/pipelineUIStore';
import { debugLogDedup } from '../lib/debugLog';

/**
 * Prefetch hook for the project dashboard.
 *
 * Subscribes to all project-related TQ queries so they fire in parallel.
 * Does NOT gate rendering — each component handles its own loading state.
 */
export function useProjectInit(projectId: string) {
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

  debugLogDedup('useProjectInit', `projectStatus=${project.status} hasData=${!!project.data} error=${project.error?.message ?? 'none'}`);
}
