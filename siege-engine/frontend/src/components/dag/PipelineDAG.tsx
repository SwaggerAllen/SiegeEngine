import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
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

export function PipelineDAG({ projectId, variant = 'pipeline' }: PipelineDAGProps) {
  const {
    nodes: pipelineNodes,
    edges: pipelineEdges,
    docNodes,
    docEdges,
    fetchDAG,
    fetchDocumentsDAG,
    selectArtifact,
    selectStage,
  } = useDAGStore();
  const { fetchArtifact, clearSelection } = useProjectStore();

  const rawNodes = variant === 'documents' ? docNodes : pipelineNodes;
  const rawEdges = variant === 'documents' ? docEdges : pipelineEdges;

  useEffect(() => {
    if (variant === 'documents') {
      fetchDocumentsDAG(projectId);
    } else {
      fetchDAG(projectId);
    }
  }, [projectId, variant, fetchDAG, fetchDocumentsDAG]);

  const layoutedNodes = useMemo(() => {
    if (rawNodes.length === 0) return [];

    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 80 });

    rawNodes.forEach((n) => g.setNode(n.id, { width: 220, height: 100 }));
    rawEdges.forEach((e) => g.setEdge(e.source, e.target));
    dagre.layout(g);

    return rawNodes.map((n) => {
      const pos = g.node(n.id);
      return {
        ...n,
        position: { x: pos.x - 110, y: pos.y - 50 },
      };
    });
  }, [rawNodes, rawEdges]);

  const [nodes, setNodes, onNodesChange] = useNodesState(layoutedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(rawEdges);

  useEffect(() => {
    setNodes(layoutedNodes);
    setEdges(rawEdges);
  }, [layoutedNodes, rawEdges, setNodes, setEdges]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: { id: string; data?: { stage_key?: string; has_artifact?: boolean } }) => {
      if (variant === 'pipeline') {
        selectStage(node.data?.stage_key ?? null);
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

  const [showMinimap, setShowMinimap] = useState(true);

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
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
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
