import { useEffect, useRef, useState, useCallback } from 'react';
import { usePipelineStore } from '../store/pipelineStore';
import { useDAGStore } from '../store/dagStore';
import { useProjectStore } from '../store/projectStore';
import type { WSEvent } from '../types/pipeline';

const INITIAL_RETRY_MS = 1000;
const MAX_RETRY_MS = 30000;
const BACKOFF_FACTOR = 2;
const FETCH_DEBOUNCE_MS = 300;

export function useWebSocket(projectId: string | undefined) {
  const wsRef = useRef<WebSocket | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryDelay = useRef(INITIAL_RETRY_MS);
  const mountedRef = useRef(true);

  // Use individual selectors so this hook doesn't re-render on every store
  // state change — only the function references matter here and they're stable.
  const updateFromWS = usePipelineStore((s) => s.updateFromWS);
  const fetchDAG = useDAGStore((s) => s.fetchDAG);
  const fetchDocumentsDAG = useDAGStore((s) => s.fetchDocumentsDAG);
  const selectArtifact = useDAGStore((s) => s.selectArtifact);
  const fetchArtifact = useProjectStore((s) => s.fetchArtifact);
  const [connected, setConnected] = useState(false);
  const debounceFetchRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (!projectId || !mountedRef.current) return;

    const token = localStorage.getItem('siege_engine_token');
    if (!token) {
      console.warn('[WS] No auth token found, skipping WebSocket connection');
      return;
    }

    // Close any existing connection
    if (wsRef.current) {
      wsRef.current.onclose = null; // prevent triggering reconnect
      wsRef.current.close();
      wsRef.current = null;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const url = `${protocol}//${host}/api/pipeline/${projectId}/ws?token=${token}`;
    console.log('[WS] Connecting to', url);

    const ws = new WebSocket(url);

    ws.onopen = () => {
      console.log('[WS] Connected');
      setConnected(true);
      retryDelay.current = INITIAL_RETRY_MS; // reset backoff on success
    };

    ws.onclose = (e) => {
      console.log('[WS] Disconnected', e.code, e.reason);
      setConnected(false);
      wsRef.current = null;

      // Don't reconnect if unmounted or if the close was a normal/clean close (1000)
      if (!mountedRef.current || e.code === 1000) return;

      const delay = retryDelay.current;
      console.log(`[WS] Reconnecting in ${delay}ms...`);
      retryTimer.current = setTimeout(() => {
        retryDelay.current = Math.min(retryDelay.current * BACKOFF_FACTOR, MAX_RETRY_MS);
        connect();
      }, delay);
    };

    ws.onerror = (e) => {
      console.error('[WS] Error', e);
    };

    ws.onmessage = (event) => {
      let data: WSEvent;
      try {
        data = JSON.parse(event.data);
      } catch {
        console.error('[WS] Failed to parse message:', event.data);
        return;
      }
      console.log('[WS] Received:', data.type, data);

      // updateFromWS applies the event to both the snapshot AND the
      // executions array locally — no HTTP fetchStatus needed.
      try {
        updateFromWS(data);
      } catch (err) {
        // createSafeStore already logged the error; swallow here so a
        // bad event doesn't kill the WebSocket connection.
        console.error('[WS] updateFromWS threw:', err);
        return;
      }

      // All store actions are safe by default (createSafeStore handles
      // unhandled rejections), so no manual .catch() needed on fire-and-forget calls.

      // Debounce DAG layout refreshes (node positions, edges, status colors).
      const needsDAGRefresh =
        data.type === 'stage_started' ||
        data.type === 'stage_completed' ||
        data.type === 'stage_awaiting_review' ||
        data.type === 'stage_failed' ||
        data.type === 'pipeline_completed' ||
        data.type === 'pipeline_cancelled' ||
        data.type === 'pipeline_paused' ||
        data.type === 'staleness_propagated' ||
        data.type === 'artifact_pruned' ||
        data.type === 'feedback_saved' ||
        data.type === 'comment_added';

      if (needsDAGRefresh) {
        if (debounceFetchRef.current) clearTimeout(debounceFetchRef.current);
        debounceFetchRef.current = setTimeout(() => {
          debounceFetchRef.current = null;
          fetchDAG(projectId);
          fetchDocumentsDAG(projectId);
        }, FETCH_DEBOUNCE_MS);
      }

      // Auto-select artifact when review is needed, but only if the user
      // isn't already viewing something — avoids stealing focus during a run
      // that generates multiple components in sequence.
      if (data.type === 'stage_awaiting_review' && data.artifact_id) {
        const currentlySelected = useDAGStore.getState().selectedArtifactId;
        if (!currentlySelected) {
          console.log('[WS] Auto-selecting artifact for review:', data.artifact_id);
          selectArtifact(data.artifact_id);
          fetchArtifact(data.artifact_id);
        } else {
          console.log('[WS] Artifact ready for review (not auto-selecting, user has selection):', data.artifact_id);
        }
      }

      // Refresh artifact after force restart so ReviewPanel clears the approved badge
      if (data.type === 'stage_failed' && data.artifact_id) {
        fetchArtifact(data.artifact_id);
      }

      // Refresh artifact content after feedback is saved
      if (data.type === 'feedback_saved' && data.artifact_id) {
        fetchArtifact(data.artifact_id);
      }

      // Refresh selected artifact when a stage completes (e.g. stale → approved)
      if (data.type === 'stage_completed' && data.artifact_id) {
        fetchArtifact(data.artifact_id);
      }

      // Refresh selected artifact when a stage starts (e.g. after rejection triggers
      // regeneration — artifact transitions to 'generating' but selectedArtifact is stale)
      if (data.type === 'stage_started') {
        const selectedId = useDAGStore.getState().selectedArtifactId;
        if (selectedId) {
          fetchArtifact(selectedId);
        }
      }
    };

    wsRef.current = ws;
  }, [projectId, updateFromWS, fetchDAG, fetchDocumentsDAG, selectArtifact, fetchArtifact]);

  useEffect(() => {
    mountedRef.current = true;
    retryDelay.current = INITIAL_RETRY_MS;
    connect();

    return () => {
      mountedRef.current = false;
      if (retryTimer.current) {
        clearTimeout(retryTimer.current);
        retryTimer.current = null;
      }
      if (debounceFetchRef.current) {
        clearTimeout(debounceFetchRef.current);
        debounceFetchRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent reconnect on intentional cleanup
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  const reconnect = useCallback(() => {
    console.log('[WS] Manual reconnect requested');
    // Cancel any pending retry
    if (retryTimer.current) {
      clearTimeout(retryTimer.current);
      retryTimer.current = null;
    }
    retryDelay.current = INITIAL_RETRY_MS;
    connect();
  }, [connect]);

  return { connected, reconnect };
}
