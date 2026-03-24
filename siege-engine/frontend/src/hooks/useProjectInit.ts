import { useEffect, useState } from 'react';
import { useProjectStore } from '../store/projectStore';
import { usePipelineStore } from '../store/pipelineStore';
import { useDAGStore } from '../store/dagStore';

/**
 * Centralized initialization for the project dashboard.
 *
 * Fetches all core data in parallel and gates child rendering via the `ready` flag.
 * Both DAG variants are pre-loaded so tab switches are instant.
 */
export function useProjectInit(projectId: string): { ready: boolean; error: Error | null } {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    setReady(false);
    setError(null);
    let cancelled = false;

    async function init() {
      // Clear stale data from a previously viewed project
      usePipelineStore.getState().reset();

      const results = await Promise.allSettled([
        useProjectStore.getState().fetchProject(projectId),
        usePipelineStore.getState().fetchConfig(projectId),
        usePipelineStore.getState().fetchStatus(projectId),
        usePipelineStore.getState().fetchRuns(projectId),
        usePipelineStore.getState().fetchBlockingPR(projectId),
        useDAGStore.getState().fetchDAG(projectId),
        useDAGStore.getState().fetchDocumentsDAG(projectId),
      ]);

      if (cancelled) return;

      // Project fetch is critical — without it we can't render anything
      const projectResult = results[0];
      if (projectResult.status === 'rejected') {
        setError(projectResult.reason instanceof Error ? projectResult.reason : new Error('Failed to load project'));
        return;
      }

      setReady(true);
    }

    init();
    return () => {
      cancelled = true;
      useProjectStore.getState().clearSelection();
    };
  }, [projectId]);

  return { ready, error };
}
