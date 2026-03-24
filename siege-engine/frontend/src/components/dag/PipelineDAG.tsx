import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { debugLog, debugLogDedup } from '../../lib/debugLog';
import type { DAGResponse } from '../../types/dag';
import type { UseQueryResult } from '@tanstack/react-query';

const nodeTypes = { stageNode: StageNode };

/** Returns a description of the first cycle found, or null if the graph is acyclic. */
function detectCycle(
  nodeIds: string[],
  edges: { source: string; target: string }[],
): string | null {
  const adj = new Map<string, string[]>();
  for (const id of nodeIds) adj.set(id, []);
  for (const e of edges) adj.get(e.source)?.push(e.target);

  const visited = new Set<string>();
  const inStack = new Set<string>();

  function dfs(node: string): string | null {
    visited.add(node);
    inStack.add(node);
    for (const neighbor of adj.get(node) ?? []) {
      if (inStack.has(neighbor)) return `${node} → ${neighbor}`;
      if (!visited.has(neighbor)) {
        const found = dfs(neighbor);
        if (found) return found;
      }
    }
    inStack.delete(node);
    return null;
  }

  for (const id of nodeIds) {
    if (!visited.has(id)) {
      const found = dfs(id);
      if (found) return found;
    }
  }
  return null;
}

const MINIMAP_COLORS: Record<string, string> = {
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

interface CachedNode {
  serialized: string;
  node: {
    id: string;
    type: string;
    data: Record<string, unknown>;
    position: { x: number; y: number };
    width: number;
    height: number;
  };
}

interface CachedEdge {
  serialized: string;
  edge: {
    id: string;
    source: string;
    target: string;
    type: string | undefined;
    animated: boolean | undefined;
  };
}

/** Returns true when every element of `next` is reference-equal to the
 *  corresponding element of `prev`. Used to keep array references stable
 *  so XYFlow's StoreUpdater skips setNodes/setEdges on unchanged polls. */
function sameElements<T>(next: T[], prev: T[]): boolean {
  return next.length === prev.length && next.every((item, i) => item === prev[i]);
}

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

  const edgeRefCache = useRef(new Map<string, CachedEdge>());
  const prevEdgesRef = useRef<CachedEdge['edge'][]>([]);

  const rawEdges = useMemo(() => {
    if (!dagData) return [];
    const currentIds = new Set(dagData.edges.map((e) => e.id));
    for (const id of edgeRefCache.current.keys()) {
      if (!currentIds.has(id)) edgeRefCache.current.delete(id);
    }
    const next = dagData.edges.map((e) => {
      const serialized = `${e.source}|${e.target}|${e.type ?? ''}|${String(e.animated ?? false)}`;
      const cached = edgeRefCache.current.get(e.id);
      if (cached && cached.serialized === serialized) return cached.edge;
      const edge = { id: e.id, source: e.source, target: e.target, type: e.type, animated: e.animated };
      edgeRefCache.current.set(e.id, { serialized, edge });
      return edge;
    });
    if (sameElements(next, prevEdgesRef.current)) return prevEdgesRef.current;
    prevEdgesRef.current = next;
    return next;
  }, [dagData]);

  const cycleError = useMemo(
    () => (dagData ? detectCycle(rawNodes.map((n) => n.id), rawEdges) : null),
    [dagData, rawNodes, rawEdges],
  );

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

  // Per-node/edge object caches. XYFlow's adoptUserNodes checks reference
  // equality (userNode === internalNode.internals.userNode) to skip rebuilding
  // node internals (position clamping, z-index, handle bounds). Stable element
  // refs also let sameElements() return the previous array unchanged, so
  // StoreUpdater's useEffect sees fieldValue === previousFieldValue and skips
  // setNodes/setEdges entirely — zero XYFlow work on polls with no real changes.
  //
  // Position stability: positions is a useMemo([topologyKey]), so when topology
  // hasn't changed the same Map instance (and same {x,y} object refs) are
  // returned — making `cached.node.position === pos` a valid cheap check.
  const nodeRefCache = useRef(new Map<string, CachedNode>());
  const prevNodesRef = useRef<CachedNode['node'][]>([]);

  // Final nodes — applies positions and injects projectId. Reuses cached object
  // references when content is unchanged so XYFlow can skip internal rebuilds.
  // width/height must be provided so XYFlow skips DOM measurement and avoids
  // the dimension-change render loop (xyflow/xyflow#3925).
  const nodes = useMemo(() => {
    const currentIds = new Set(rawNodes.map((n) => n.id));
    for (const id of nodeRefCache.current.keys()) {
      if (!currentIds.has(id)) nodeRefCache.current.delete(id);
    }
    const next = rawNodes.map((n) => {
      const pos = positions.get(n.id) ?? { x: 0, y: 0 };
      const serialized = JSON.stringify(n.data) + '|' + projectId;
      const cached = nodeRefCache.current.get(n.id);
      if (cached && cached.serialized === serialized && cached.node.position === pos) {
        return cached.node;
      }
      const node = {
        ...n,
        data: { ...n.data, projectId },
        position: pos,
        width: 220,
        height: 100,
      };
      nodeRefCache.current.set(n.id, { serialized, node });
      return node;
    });
    if (sameElements(next, prevNodesRef.current)) return prevNodesRef.current;
    prevNodesRef.current = next;
    return next;
  }, [rawNodes, positions, projectId]);

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

  const minimapNodeColor = useCallback((n: { data?: Record<string, unknown> }) => {
    const artifactType = n.data?.artifact_type as string;
    if (artifactType === 'component_map' || artifactType === 'sub_component_map') return '#818cf8';
    return MINIMAP_COLORS[n.data?.status as string] || '#6b7280';
  }, []);

  const [showMinimap, setShowMinimap] = useState(true);

  debugLogDedup(`DAG.render.${variant}`, `variant=${variant} hasData=${!!dagData} nodes=${rawNodes.length} status=${status} isLoading=${isLoading} isFetching=${isFetching} error=${error ?? 'none'}`);

  if (isError) {
    return (
      <div className="flex items-center justify-center h-full text-red-400">
        Failed to load {variant === 'documents' ? 'documents' : 'pipeline'}: {String(error)}
      </div>
    );
  }

  if (cycleError) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 text-red-400">
        <span className="font-semibold">Cycle detected in DAG</span>
        <span className="text-xs text-red-300 font-mono">{cycleError}</span>
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
          nodeColor={minimapNodeColor}
        />
      )}
    </ReactFlow>
  );
}
