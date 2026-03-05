import { useCallback, useEffect, useMemo } from 'react';
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

export function PipelineDAG({ projectId }: { projectId: string }) {
  const { nodes: rawNodes, edges: rawEdges, fetchDAG, selectArtifact } = useDAGStore();
  const { fetchArtifact } = useProjectStore();

  useEffect(() => {
    fetchDAG(projectId);
  }, [projectId]);

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
  }, [layoutedNodes, rawEdges]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: any) => {
      // Only load artifact details for nodes that have an artifact
      const hasArtifact = node.data?.has_artifact;
      if (hasArtifact) {
        selectArtifact(node.id);
        fetchArtifact(node.id);
      }
    },
    [selectArtifact, fetchArtifact]
  );

  if (rawNodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        Loading pipeline stages...
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
      fitView
      className="bg-gray-900"
    >
      <Background color="#374151" gap={20} />
      <Controls className="!bg-gray-800 !border-gray-600 [&>button]:!bg-gray-700 [&>button]:!text-white [&>button]:!border-gray-600" />
      <MiniMap
        className="!bg-gray-800"
        nodeColor={(n) => {
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
    </ReactFlow>
  );
}
