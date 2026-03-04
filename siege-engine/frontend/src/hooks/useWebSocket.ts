import { useEffect, useRef, useState } from 'react';
import { usePipelineStore } from '../store/pipelineStore';
import { useDAGStore } from '../store/dagStore';
import type { WSEvent } from '../types/pipeline';

export function useWebSocket(projectId: string | undefined) {
  const wsRef = useRef<WebSocket | null>(null);
  const { updateFromWS } = usePipelineStore();
  const { fetchDAG } = useDAGStore();
  const [connected, setConnected] = useState(false);
  const { fetchStatus } = usePipelineStore();

  useEffect(() => {
    if (!projectId) return;

    const token = localStorage.getItem('siege_engine_token');
    if (!token) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const ws = new WebSocket(
      `${protocol}//${host}/api/pipeline/${projectId}/ws?token=${token}`
    );

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);

    ws.onmessage = (event) => {
      const data: WSEvent = JSON.parse(event.data);
      updateFromWS(data);

      if (
        data.type === 'stage_completed' ||
        data.type === 'stage_awaiting_review' ||
        data.type === 'pipeline_completed' ||
        data.type === 'pipeline_paused' ||
        data.type === 'staleness_propagated'
      ) {
        fetchDAG(projectId);
        fetchStatus(projectId);
      }
    };

    wsRef.current = ws;
    return () => ws.close();
  }, [projectId]);

  return { connected };
}
