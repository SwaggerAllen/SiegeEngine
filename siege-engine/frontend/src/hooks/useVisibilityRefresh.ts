import { useEffect, useRef } from 'react';

const STALE_THRESHOLD_MS = 30_000; // 30 seconds

/**
 * Reconnects the WebSocket when the user returns to the tab after 30+ seconds.
 *
 * Data refetching is now handled by TanStack Query's built-in refetchOnWindowFocus
 * (with staleTime: 30_000 matching this threshold). This hook only handles WS
 * reconnection since browser-backgrounded connections commonly drop.
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
          console.log(`[VisibilityRefresh] Tab refocused after ${Math.round(elapsed / 1000)}s — reconnecting WS`);
          reconnectWS();
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [projectId, reconnectWS]);
}
