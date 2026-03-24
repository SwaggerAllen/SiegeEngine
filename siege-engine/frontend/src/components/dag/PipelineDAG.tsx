import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
} from '@xyflow/react';
import dagre from 'dagre';
import '@xyflow/react/dist/style.css';

import { useDAGStore } from '../../store/dagStore';
import { useDAGData, useDocumentsDAGData } from '../../hooks/queries/useDAGQueries';
import { StageNode } from './StageNode';
import { debugLogDedup } from '../../lib/debugLog';
import type { DAGResponse } from '../../types/dag';
import type { UseQueryResult } from '@tanstack/react-query';

const nodeTypes = { stageNode: StageNode };

interface PipelineDAGProps {
  projectId: string;
  variant?: 'pipeline' | 'documents';
}

// Public entry point: picks the right inner component based on variant so
// each view subscribes to exactly one TQ query (no cross-subscription churn).
export function PipelineDAG({ projectId, variant = 'pipeline' }: PipelineDAGProps) {
  return (
    <ReactFlowProvider>
      {variant === 'documents'
        ? <DocumentsDAGInner projectId={projectId} />
        : <WorkflowDAGInner projectId={projectId} />
      }
    </ReactFlowProvider>
  );
}

function WorkflowDAGInner({ projectId }: { projectId: string }) {
  const query = useDAGData(projectId);
  return <DAGCanvas projectId={projectId} variant="pipeline" query={query} />;
}

function DocumentsDAGInner({ projectId }: { projectId: string }) {
  const query = useDocumentsDAGData(projectId);

  useEffect(() => {
    debugLog('DAG.lifecycle', `DocumentsDAGInner MOUNT projectId=${projectId}`);
    return () => { debugLog('DAG.lifecycle', `DocumentsDAGInner UNMOUNT projectId=${projectId}`); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <DAGCanvas projectId={projectId} variant="documents" query={query} />;
}

// ---------------------------------------------------------------------------
// DAGCanvas — pure rendering, no TQ subscriptions
// ---------------------------------------------------------------------------

interface DAGCanvasProps {
  projectId: string;
  variant: 'pipeline' | 'documents';
  query: UseQueryResult<DAGResponse>;
}

function DAGCanvas({ projectId, variant, query }: DAGCanvasProps) {
  const { data: dagData, status, isLoading, isFetching, error, isError } = query;

  // Map TQ response into ReactFlow nodes/edges
  const rawNodes = useMemo(() => {
    if (!dagData) return [];
    return dagData.nodes.map((n) => ({
      id: n.id,
      type: n.type,
      data: n.data as unknown as Record<string, unknown>,
      position: n.position,
    }));
  }, [dagData]);

  const rawEdges = useMemo(() => {
    if (!dagData) return [];
    return dagData.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: e.type,
      animated: e.animated,
    }));
  }, [dagData]);

  // === UI state from Zustand (selection only) ===
  const selectArtifact = useDAGStore((s) => s.selectArtifact);
  const selectStage = useDAGStore((s) => s.selectStage);
  const clearSelection = useDAGStore((s) => s.clearSelection);

  // === Dagre layout ===
  // Topology key — stable primitive that only changes when node IDs or edge
  // connections change. Status/data field updates do NOT change it, so the
  // expensive dagre layout step is skipped on every pipeline tick.
  const topologyKey = useMemo(
    () =>
      rawNodes.map((n) => n.id).join('\0') +
      '|' +
      rawEdges.map((e) => `${e.source}>${e.target}`).join('\0'),
    [rawNodes, rawEdges],
  );

  // Positions — only re-runs when topology changes.
  const positions = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    if (rawNodes.length === 0) return map;
    try {
      const g = new dagre.graphlib.Graph();
      g.setDefaultEdgeLabel(() => ({}));
      g.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 80 });
      rawNodes.forEach((n) => g.setNode(n.id, { width: 220, height: 100 }));
      rawEdges.forEach((e) => g.setEdge(e.source, e.target));
      dagre.layout(g);
      rawNodes.forEach((n) => {
        const pos = g.node(n.id);
        map.set(n.id, pos ? { x: pos.x - 110, y: pos.y - 50 } : { x: 0, y: 0 });
      });
    } catch (err) {
      console.error('[PipelineDAG] Dagre layout failed:', err);
      rawNodes.forEach((n, i) => map.set(n.id, { x: 0, y: i * 120 }));
    }
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topologyKey]); // rawNodes/rawEdges intentionally excluded: topologyKey captures when layout must change

  // Final nodes — cheap map that applies positions and injects projectId.
  // Re-runs on data changes (status, version, etc.) without re-running dagre.
  // width/height must be provided so XYFlow skips DOM measurement and avoids
  // the dimension-change render loop (xyflow/xyflow#3925).
  const nodes = useMemo(
    () =>
      rawNodes.map((n) => ({
        ...n,
        data: { ...n.data, projectId },
        position: positions.get(n.id) ?? { x: 0, y: 0 },
        width: 220,
        height: 100,
      })),
    [rawNodes, positions, projectId],
  );

  // === Click handlers ===
  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: { id: string; data?: Record<string, unknown> }) => {
      if (variant === 'pipeline') {
        selectStage((node.data?.stage_key as string) ?? null);
      } else {
        if (node.data?.has_artifact) {
          selectArtifact(node.id);
        }
      }
    },
    [variant, selectStage, selectArtifact]
  );

  const onPaneClick = useCallback(() => {
    clearSelection();
  }, [clearSelection]);

  // No-op handlers required in controlled mode so XYFlow knows changes are
  // intentionally discarded (read-only DAG). Without these, XYFlow keeps
  // trying to reconcile internal state against the nodes/edges props.
  const onNodesChange = useCallback(() => {}, []);
  const onEdgesChange = useCallback(() => {}, []);

  const [showMinimap, setShowMinimap] = useState(true);

  debugLogDedup(`DAG.render.${variant}`, `variant=${variant} hasData=${!!dagData} nodes=${rawNodes.length} status=${status} isLoading=${isLoading} isFetching=${isFetching} error=${error ?? 'none'}`);

  if (isError) {
    return (
      <div className="flex items-center justify-center h-full text-red-400">
        Failed to load {variant === 'documents' ? 'documents' : 'pipeline'}: {String(error)}
      </div>
    );
  }

  if (!dagData || rawNodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        {isLoading
          ? (variant === 'documents' ? 'Loading documents...' : 'Loading pipeline stages...')
          : (variant === 'documents' ? 'No documents yet' : 'No pipeline stages yet')}
      </div>
    );
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={rawEdges}
      nodeTypes={nodeTypes}
      onNodeClick={onNodeClick}
      onPaneClick={onPaneClick}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      fitView
      className="bg-gray-900"
    >
      <Background color="#374151" gap={20} />
      <Controls className="!bg-gray-800 !border-gray-600 [&>button]:!bg-gray-700 [&>button]:!text-white [&>button]:!border-gray-600" />
      <button
        onClick={() => setShowMinimap((v) => !v)}
        className="absolute top-2 right-2 z-10 px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white text-xs rounded border border-gray-600"
        title={showMinimap ? 'Hide minimap' : 'Show minimap'}
      >
        {showMinimap ? 'Hide Map' : 'Show Map'}
      </button>
      {showMinimap && (
        <MiniMap
          className="!bg-gray-800"
          nodeColor={(n) => {
            const artifactType = n.data?.artifact_type as string;
            if (artifactType === 'component_map' || artifactType === 'sub_component_map') {
              return '#818cf8';
            }
            const status = n.data?.status as string;
            const colors: Record<string, string> = {
              approved: '#22c55e',
              awaiting_review: '#eab308',
              generating: '#3b82f6',
              running: '#3b82f6',
              ai_reviewing: '#a855f7',
              stale: '#f97316',
              rejected: '#ef4444',
              failed: '#ef4444',
              pending: '#6b7280',
            };
            return colors[status] || '#6b7280';
          }}
        />
      )}
    </ReactFlow>
  );
}
