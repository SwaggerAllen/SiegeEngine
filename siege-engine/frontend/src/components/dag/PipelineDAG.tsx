import { useCallback, useMemo } from 'react';
// import { useState } from 'react';  // Layer 5b: restore for MiniMap toggle
import { useSafeEffect } from '../../hooks/useSafe';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  // Controls,   // Layer 5b: restore
  // MiniMap,     // Layer 5b: restore
} from '@xyflow/react';
import dagre from 'dagre';
import '@xyflow/react/dist/style.css';

import { useDAGStore } from '../../store/dagStore';
import { useProjectStore } from '../../store/projectStore';
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
  // === LAYER 1: Store selectors ===
  const pipelineNodes = useDAGStore((s) => s.nodes);
  const pipelineEdges = useDAGStore((s) => s.edges);
  const docNodes = useDAGStore((s) => s.docNodes);
  const docEdges = useDAGStore((s) => s.docEdges);
  const fetchDAG = useDAGStore((s) => s.fetchDAG);
  const fetchDocumentsDAG = useDAGStore((s) => s.fetchDocumentsDAG);
  const selectArtifact = useDAGStore((s) => s.selectArtifact);
  const selectStage = useDAGStore((s) => s.selectStage);
  const fetchArtifact = useProjectStore((s) => s.fetchArtifact);
  const clearSelection = useProjectStore((s) => s.clearSelection);

  const rawNodes = variant === 'documents' ? docNodes : pipelineNodes;
  const rawEdges = variant === 'documents' ? docEdges : pipelineEdges;
  // Keep subscriptions active but satisfy noUnusedLocals
  void selectArtifact; void selectStage;
  void fetchArtifact; void clearSelection;
  console.log('[PipelineDAG] render — rawNodes:', rawNodes.length, 'rawEdges:', rawEdges.length);

  // === LAYER 2: Fetch effect ===
  useSafeEffect('dag-fetch', () => {
    if (variant === 'documents') {
      fetchDocumentsDAG(projectId);
    } else {
      fetchDAG(projectId);
    }
  }, [projectId, variant, fetchDAG, fetchDocumentsDAG]);

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


  // === LAYER 5a: real nodes/edges, default node type (no StageNode) ===
  // Testing whether the loop is caused by StageNode, MiniMap, or just
  // having real data in ReactFlow.  nodeTypes / Controls / MiniMap stripped.
  void nodeTypes; // suppress unused — will restore in 5b

  if (rawNodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        {variant === 'documents' ? 'Loading documents...' : 'Loading pipeline stages...'}
      </div>
    );
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={rawEdges}
      onNodeClick={onNodeClick}
      onPaneClick={onPaneClick}
      fitView
      className="bg-gray-900"
    >
      <Background color="#374151" gap={20} />
    </ReactFlow>
  );
}
