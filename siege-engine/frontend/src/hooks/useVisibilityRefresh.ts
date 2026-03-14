import { useEffect, useRef } from 'react';
import { useProjectStore } from '../store/projectStore';
import { usePipelineStore } from '../store/pipelineStore';
import { useDAGStore } from '../store/dagStore';

const STALE_THRESHOLD_MS = 30_000; // 30 seconds

/**
 * Triggers a full project state refresh when the user returns to the tab
 * after being away for 30+ seconds.  Also reconnects the WebSocket since
 * browser-backgrounded connections commonly drop.
 */
export function useVisibilityRefresh(
  projectId: string | undefined,
  reconnectWS: () => void,
): void {
  const hiddenAtRef = useRef<number | null>(null);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        hiddenAtRef.current = Date.now();
      } else if (document.visibilityState === 'visible' && hiddenAtRef.current) {
        const elapsed = Date.now() - hiddenAtRef.current;
        hiddenAtRef.current = null;

        if (elapsed >= STALE_THRESHOLD_MS && projectId) {
          console.log(`[VisibilityRefresh] Tab refocused after ${Math.round(elapsed / 1000)}s — refreshing`);

          // Pull fresh state from all stores
          useProjectStore.getState().fetchProject(projectId);
          usePipelineStore.getState().fetchConfig(projectId);
          usePipelineStore.getState().fetchStatus(projectId);
          usePipelineStore.getState().fetchRuns(projectId);
          useDAGStore.getState().fetchDAG(projectId);
          useDAGStore.getState().fetchDocumentsDAG(projectId);

          // Reconnect WS in case the connection went stale
          reconnectWS();
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [projectId, reconnectWS]);
}
