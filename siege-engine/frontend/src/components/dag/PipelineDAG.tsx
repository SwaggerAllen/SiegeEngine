import { useCallback, useMemo, useState } from 'react';
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
import { useProjectStore } from '../../store/projectStore';
import { useDAGData, useDocumentsDAGData } from '../../hooks/queries/useDAGQueries';
import { StageNode } from './StageNode';

const nodeTypes = { stageNode: StageNode };

interface PipelineDAGProps {
  projectId: string;
  variant?: 'pipeline' | 'documents';
}

export function PipelineDAG(props: PipelineDAGProps) {
  return (
    <ReactFlowProvider>
      <PipelineDAGInner {...props} />
    </ReactFlowProvider>
  );
}

function PipelineDAGInner({ projectId, variant = 'pipeline' }: PipelineDAGProps) {
  // === LAYER 1: Read DAG data from TanStack Query ===
  const workflowQuery = useDAGData(projectId);
  const documentsQuery = useDocumentsDAGData(projectId);

  const activeQuery = variant === 'documents' ? documentsQuery : workflowQuery;
  const dagData = activeQuery.data;

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
  const fetchArtifact = useProjectStore((s) => s.fetchArtifact);
  const clearSelection = useProjectStore((s) => s.clearSelection);

  // === LAYER 3: Dagre layout ===
  const nodes = useMemo(() => {
    if (rawNodes.length === 0) return [];

    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 80 });

    rawNodes.forEach((n) => g.setNode(n.id, { width: 220, height: 100 }));
    rawEdges.forEach((e) => g.setEdge(e.source, e.target));
    dagre.layout(g);

    return rawNodes.map((n) => {
      const pos = g.node(n.id);
      if (!pos) return { ...n, data: { ...n.data, projectId }, position: { x: 0, y: 0 } };
      return {
        ...n,
        data: { ...n.data, projectId },
        position: { x: pos.x - 110, y: pos.y - 50 },
      };
    });
  }, [rawNodes, rawEdges, projectId]);

  // === LAYER 4: Click handlers ===
  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: { id: string; data?: Record<string, unknown> }) => {
      if (variant === 'pipeline') {
        selectStage((node.data?.stage_key as string) ?? null);
      } else {
        const hasArtifact = node.data?.has_artifact;
        if (hasArtifact) {
          selectArtifact(node.id);
          fetchArtifact(node.id);
        }
      }
    },
    [variant, selectStage, selectArtifact, fetchArtifact]
  );

  const onPaneClick = useCallback(() => {
    selectStage(null);
    selectArtifact(null);
    clearSelection();
  }, [selectStage, selectArtifact, clearSelection]);

  // === LAYER 5: Render ===
  const [showMinimap, setShowMinimap] = useState(true);

  if (activeQuery.isError) {
    return (
      <div className="flex items-center justify-center h-full text-red-400">
        Failed to load {variant === 'documents' ? 'documents' : 'pipeline'}: {String(activeQuery.error)}
      </div>
    );
  }

  if (!dagData || rawNodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        {activeQuery.isLoading
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
