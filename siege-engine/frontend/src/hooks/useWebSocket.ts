import { useEffect, useRef, useState } from 'react';
import { usePipelineStore } from '../store/pipelineStore';
import { useDAGStore } from '../store/dagStore';
import { useProjectStore } from '../store/projectStore';
import type { WSEvent } from '../types/pipeline';

export function useWebSocket(projectId: string | undefined) {
  const wsRef = useRef<WebSocket | null>(null);
  const { updateFromWS } = usePipelineStore();
  const { fetchDAG, selectArtifact } = useDAGStore();
  const { fetchArtifact } = useProjectStore();
  const [connected, setConnected] = useState(false);
  const { fetchStatus } = usePipelineStore();

  useEffect(() => {
    if (!projectId) return;

    const token = localStorage.getItem('siege_engine_token');
    if (!token) {
      console.warn('[WS] No auth token found, skipping WebSocket connection');
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const url = `${protocol}//${host}/api/pipeline/${projectId}/ws?token=${token}`;
    console.log('[WS] Connecting to', url);

    const ws = new WebSocket(url);

    ws.onopen = () => {
      console.log('[WS] Connected');
      setConnected(true);
    };
    ws.onclose = (e) => {
      console.log('[WS] Disconnected', e.code, e.reason);
      setConnected(false);
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
        data.type === 'staleness_propagated'
      ) {
        fetchDAG(projectId);
        fetchStatus(projectId);
      }

      // Auto-select artifact when review is needed
      if (data.type === 'stage_awaiting_review' && data.artifact_id) {
        console.log('[WS] Auto-selecting artifact for review:', data.artifact_id);
        selectArtifact(data.artifact_id);
        fetchArtifact(data.artifact_id);
      }
    };

    wsRef.current = ws;
    return () => ws.close();
  }, [projectId]);

  return { connected };
}
