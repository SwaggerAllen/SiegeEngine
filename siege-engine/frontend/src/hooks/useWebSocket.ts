import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useDAGStore } from '../store/dagStore';
import { pipelineKeys } from './queries/usePipelineQueries';
import { dagKeys } from './queries/useDAGQueries';
import { projectKeys } from './queries/useProjectQueries';
import type { WSEvent } from '../types/pipeline';

const INITIAL_RETRY_MS = 1000;
const MAX_RETRY_MS = 30000;
const BACKOFF_FACTOR = 2;
const FETCH_DEBOUNCE_MS = 300;

const DAG_REFRESH_EVENTS = new Set([
  'stage_started',
  'stage_completed',
  'stage_awaiting_review',
  'stage_failed',
  'pipeline_completed',
  'pipeline_cancelled',
  'pipeline_paused',
  'staleness_propagated',
  'artifact_pruned',
]);

export function useWebSocket(projectId: string | undefined) {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryDelay = useRef(INITIAL_RETRY_MS);
  const mountedRef = useRef(true);
  const debounceFetchRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [connected, setConnected] = useState(false);

  // Keep queryClient in a ref so `connect` doesn't close over a stale reference
  // and doesn't need queryClient as a dependency (it's stable but this is safer).
  const queryClientRef = useRef(queryClient);
  queryClientRef.current = queryClient;

  const connect = useCallback(() => {
    if (!projectId || !mountedRef.current) return;

    const token = localStorage.getItem('siege_engine_token');
    if (!token) {
      console.warn('[WS] No auth token found, skipping WebSocket connection');
      return;
    }

    // Close any existing connection without triggering the reconnect path
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/api/pipeline/${projectId}/ws?token=${token}`;
    console.log('[WS] Connecting to', url);

    const ws = new WebSocket(url);

    ws.onopen = () => {
      console.log('[WS] Connected');
      setConnected(true);
      retryDelay.current = INITIAL_RETRY_MS;
    };

    ws.onclose = (e) => {
      console.log('[WS] Disconnected', e.code, e.reason);
      setConnected(false);
      wsRef.current = null;

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
        data = JSON.parse(event.data) as WSEvent;
      } catch {
        console.error('[WS] Failed to parse message:', event.data);
        return;
      }
      console.log('[WS] Received:', data.type);

      const qc = queryClientRef.current;

      // Always refresh pipeline status (running state, paused state, etc.)
      qc.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });

      // Debounce DAG layout refreshes
      if (DAG_REFRESH_EVENTS.has(data.type)) {
        if (debounceFetchRef.current) clearTimeout(debounceFetchRef.current);
        debounceFetchRef.current = setTimeout(() => {
          qc.invalidateQueries({ queryKey: dagKeys.workflow(projectId) });
          qc.invalidateQueries({ queryKey: dagKeys.documents(projectId) });
        }, FETCH_DEBOUNCE_MS);
      }

      // Auto-select artifact when review is needed (only if user has nothing selected)
      if (data.type === 'stage_awaiting_review' && data.artifact_id) {
        const currentlySelected = useDAGStore.getState().selectedArtifactId;
        if (!currentlySelected) {
          console.log('[WS] Auto-selecting artifact for review:', data.artifact_id);
          useDAGStore.getState().selectArtifact(data.artifact_id);
        }
        qc.invalidateQueries({ queryKey: projectKeys.artifact(data.artifact_id) });
      }

      // Refresh artifact after force restart, feedback save, or stage completion
      if (
        (data.type === 'stage_failed' ||
          data.type === 'feedback_saved' ||
          data.type === 'stage_completed') &&
        data.artifact_id
      ) {
        qc.invalidateQueries({ queryKey: projectKeys.artifact(data.artifact_id) });
      }

      // Refresh selected artifact when a stage starts (e.g. rejection triggers regen)
      if (data.type === 'stage_started') {
        const selectedId = useDAGStore.getState().selectedArtifactId;
        if (selectedId) {
          qc.invalidateQueries({ queryKey: projectKeys.artifact(selectedId) });
        }
      }

      // Refresh artifact on comment events
      if (
        (data.type === 'comment_added' ||
          data.type === 'comment_updated' ||
          data.type === 'comment_deleted') &&
        data.artifact_id
      ) {
        qc.invalidateQueries({ queryKey: projectKeys.artifact(data.artifact_id) });
      }
    };

    wsRef.current = ws;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

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
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  const reconnect = useCallback(() => {
    console.log('[WS] Manual reconnect requested');
    if (retryTimer.current) {
      clearTimeout(retryTimer.current);
      retryTimer.current = null;
    }
    retryDelay.current = INITIAL_RETRY_MS;
    connect();
  }, [connect]);

  return { connected, reconnect };
}
