import { useCallback } from 'react';

// === WS DISABLED FOR DEBUGGING ===
// Entire WebSocket hook stubbed out to isolate whether WS events
// cause the re-render loop during active runs.
// If the loop stops with this stub, the problem is WS-driven state churn.
// If the loop persists, the problem is in initial HTTP fetches or rendering.

export function useWebSocket(_projectId: string | undefined) {
  const reconnect = useCallback(() => {
    console.log('[WS] DISABLED — reconnect is a no-op');
  }, []);

  return { connected: false, reconnect };
}
