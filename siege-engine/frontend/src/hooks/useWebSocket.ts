import { useEffect, useRef, useState, useCallback } from 'react';
import { usePipelineStore } from '../store/pipelineStore';
import { useDAGStore } from '../store/dagStore';
import { useProjectStore } from '../store/projectStore';
import type { WSEvent } from '../types/pipeline';

const INITIAL_RETRY_MS = 1000;
const MAX_RETRY_MS = 30000;
const BACKOFF_FACTOR = 2;

export function useWebSocket(projectId: string | undefined) {
  const wsRef = useRef<WebSocket | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryDelay = useRef(INITIAL_RETRY_MS);
  const mountedRef = useRef(true);

  const { updateFromWS, fetchStatus } = usePipelineStore();
  const { fetchDAG, fetchDocumentsDAG, selectArtifact } = useDAGStore();
  const { fetchArtifact } = useProjectStore();
  const [connected, setConnected] = useState(false);

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
      const data: WSEvent = JSON.parse(event.data);
      console.log('[WS] Received:', data.type, data);
      updateFromWS(data);

      // Refresh DAG and status on state-changing events
      if (
        data.type === 'stage_started' ||
        data.type === 'stage_completed' ||
        data.type === 'stage_awaiting_review' ||
        data.type === 'stage_progress' ||
        data.type === 'stage_failed' ||
        data.type === 'pipeline_completed' ||
        data.type === 'pipeline_paused' ||
        data.type === 'staleness_propagated' ||
        data.type === 'feedback_saved' ||
        data.type === 'comment_added' ||
        data.type === 'artifact_pruned'
      ) {
        fetchDAG(projectId);
        fetchDocumentsDAG(projectId);
        fetchStatus(projectId);
      }

      // Auto-select artifact when review is needed
      if (data.type === 'stage_awaiting_review' && data.artifact_id) {
        console.log('[WS] Auto-selecting artifact for review:', data.artifact_id);
        selectArtifact(data.artifact_id);
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
    };

    wsRef.current = ws;
  }, [projectId, updateFromWS, fetchStatus, fetchDAG, fetchDocumentsDAG, selectArtifact, fetchArtifact]);

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
