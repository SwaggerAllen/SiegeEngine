import { useEffect, useRef } from 'react';
import { useProject } from './queries/useProjectQueries';
import { usePipelineConfig, usePipelineStatus, usePipelineRuns, useBlockingPR } from './queries/usePipelineQueries';
import { useDAGData, useDocumentsDAGData } from './queries/useDAGQueries';
import { useDAGStore } from '../store/dagStore';
import { usePipelineUIStore } from '../store/pipelineUIStore';
import { debugLogDedup } from '../lib/debugLog';

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
      useDAGStore.getState().clearSelection();
    };
  }, [projectId]);

  // --- Gate rendering on critical data ---
  // Once ready for a given projectId, never flip back to false.
  // TQ can transiently report pending (StrictMode double-mount, cache eviction,
  // HMR) but the dashboard should never unmount children once they've rendered.
  const readyRef = useRef(false);
  const lastProjectIdRef = useRef(projectId);
  if (lastProjectIdRef.current !== projectId) {
    // New project — reset the latch
    readyRef.current = false;
    lastProjectIdRef.current = projectId;
  }
  if (project.data) {
    readyRef.current = true;
  }
  const ready = readyRef.current;

  const error = project.error instanceof Error
    ? project.error
    : project.error
      ? new Error('Failed to load project')
      : null;

  debugLogDedup('useProjectInit', `ready=${ready} projectStatus=${project.status} error=${error?.message ?? 'none'}`);

  return { ready, error };
}
