import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  useReactFlow,
} from '@xyflow/react';
import dagre from 'dagre';
import '@xyflow/react/dist/style.css';

import { useDAGStore } from '../../store/dagStore';
import { useDAGData, useDocumentsDAGData } from '../../hooks/queries/useDAGQueries';
import { StageNode } from './StageNode';
import { DocumentTreeView } from './DocumentTreeView';
import { debugLog, debugLogDedup } from '../../lib/debugLog';
import { RESTARTABLE_STATUSES } from '../../types/pipeline';
import type { DAGResponse } from '../../types/dag';
import type { UseQueryResult } from '@tanstack/react-query';

const nodeTypes = { stageNode: StageNode };

const CANCELABLE_EXEC_STATUSES = new Set(['running', 'ai_review', 'pending']);

/** Estimate node height based on which sections will render in StageNode. */
function estimateNodeHeight(data: Record<string, unknown>): number {
  let h = 60; // base: padding (24) + label + status line

  // Component key adds a second text line
  if (data.component_key) h += 18;

  const hasPromptInfo = !!data.prompt_info;
  const executionStatus = data.execution_status as string | null;

  const canCancel = !!(
    data.execution_id
    && executionStatus
    && CANCELABLE_EXEC_STATUSES.has(executionStatus)
  );

  const canRestart = !!(
    data.execution_id
    && executionStatus
    && RESTARTABLE_STATUSES.has(executionStatus)
  );

  // Cancel or restart button
  if (canCancel || (canRestart && !canCancel)) h += 32;

  // Prompt info section (separator + model line)
  if (hasPromptInfo) h += 30;

  return h;
}

/** Returns a description of the first cycle found, or null if the graph is acyclic. */
function detectCycle(
  nodeIds: string[],
  edges: { source: string; target: string }[],
): string | null {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  for (const id of nodeIds) g.setNode(id, {});
  for (const e of edges) g.setEdge(e.source, e.target);
  if (dagre.graphlib.alg.isAcyclic(g)) return null;
  const cycles = dagre.graphlib.alg.findCycles(g);
  return cycles.length > 0 ? cycles[0].join(' → ') : 'unknown cycle';
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
  const [viewMode, setViewMode] = useState<'dag' | 'tree'>('dag');

  const searchableNodes = useMemo<SearchableNode[]>(() => {
    if (!query.data) return [];
    return query.data.nodes.map((n) => ({
      id: n.id,
      label: n.data.label,
      componentKey: n.data.component_key,
      status: n.data.status,
      stageKey: n.data.stage_key,
      artifactType: n.data.artifact_type,
      hasArtifact: n.data.has_artifact,
    }));
  }, [query.data]);

  useEffect(() => {
    debugLog('DAG.lifecycle', `DocumentsDAGInner MOUNT projectId=${projectId}`);
    return () => { debugLog('DAG.lifecycle', `DocumentsDAGInner UNMOUNT projectId=${projectId}`); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (viewMode === 'tree') {
    return (
      <div className="h-full relative">
        <DocumentTreeView nodes={searchableNodes} edges={query.data?.edges ?? []} />
        <button
          onClick={() => setViewMode('dag')}
          className="absolute top-2 right-2 z-10 px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white text-xs rounded border border-gray-600"
          title="Switch to DAG view"
        >
          DAG View
        </button>
      </div>
    );
  }

  return <DAGCanvas projectId={projectId} variant="documents" query={query} onTreeView={() => setViewMode('tree')} />;
}

// ---------------------------------------------------------------------------
// DAGSearchBar — floating search overlay for finding nodes
// ---------------------------------------------------------------------------

export interface SearchableNode {
  id: string;
  label: string;
  componentKey: string | null;
  status: string;
  stageKey: string;
  artifactType: string;
  hasArtifact: boolean;
}

export function DAGSearchBar({
  nodes,
  variant,
}: {
  nodes: SearchableNode[];
  variant: 'pipeline' | 'documents';
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [highlightIdx, setHighlightIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const selectArtifact = useDAGStore((s) => s.selectArtifact);
  const selectStage = useDAGStore((s) => s.selectStage);
  const { setCenter, getNode } = useReactFlow();

  const matches = useMemo(() => {
    if (!query.trim()) return [];
    const q = query.toLowerCase();
    return nodes.filter(
      (n) =>
        n.label.toLowerCase().includes(q) ||
        (n.componentKey && n.componentKey.toLowerCase().includes(q)) ||
        n.status.toLowerCase().includes(q) ||
        n.stageKey.replace(/_/g, ' ').toLowerCase().includes(q),
    );
  }, [query, nodes]);

  useEffect(() => {
    setHighlightIdx(0);
  }, [matches.length]);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const selectNode = useCallback(
    (node: SearchableNode) => {
      if (variant === 'pipeline') {
        selectStage(node.stageKey);
      } else {
        if (node.hasArtifact) selectArtifact(node.id);
      }
      // Pan to the selected node
      const rfNode = getNode(node.id);
      if (rfNode) {
        const x = rfNode.position.x + (rfNode.width ?? 220) / 2;
        const y = rfNode.position.y + (rfNode.height ?? 100) / 2;
        setCenter(x, y, { zoom: 1.2, duration: 300 });
      }
      setOpen(false);
      setQuery('');
    },
    [variant, selectStage, selectArtifact, setCenter, getNode],
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightIdx((i) => Math.min(i + 1, matches.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && matches[highlightIdx]) {
      e.preventDefault();
      selectNode(matches[highlightIdx]);
    } else if (e.key === 'Escape') {
      setOpen(false);
      setQuery('');
      inputRef.current?.blur();
    }
  };

  const STATUS_DOTS: Record<string, string> = {
    approved: 'bg-green-500',
    awaiting_review: 'bg-yellow-500',
    generating: 'bg-blue-500',
    running: 'bg-blue-500',
    ai_reviewing: 'bg-purple-500',
    stale: 'bg-orange-500',
    rejected: 'bg-red-500',
    failed: 'bg-red-700',
    pending: 'bg-gray-500',
  };

  return (
    <div ref={containerRef} className="absolute top-2 left-2 z-10 w-64">
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder="Search nodes..."
          className="w-full px-3 py-2 bg-gray-800 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none placeholder-gray-500 min-h-[44px]"
        />
        {query && (
          <button
            onClick={() => { setQuery(''); setOpen(false); }}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 text-sm min-h-[44px] min-w-[44px] flex items-center justify-center"
          >
            ✕
          </button>
        )}
      </div>
      {open && query.trim() && (
        <div className="mt-1 max-h-60 overflow-y-auto bg-gray-800 border border-gray-600 rounded shadow-lg">
          {matches.length === 0 ? (
            <div className="px-3 py-2 text-sm text-gray-500">No matches</div>
          ) : (
            matches.map((node, i) => (
              <button
                key={node.id}
                onClick={() => selectNode(node)}
                onMouseEnter={() => setHighlightIdx(i)}
                className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2 min-h-[44px] ${
                  i === highlightIdx ? 'bg-gray-700' : 'hover:bg-gray-700/50'
                }`}
              >
                <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${STATUS_DOTS[node.status] ?? 'bg-gray-500'}`} />
                <span className="text-white truncate">{node.label}</span>
                {node.componentKey && (
                  <span className="text-gray-500 truncate ml-auto">{node.componentKey}</span>
                )}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// DAGCanvas — pure rendering, no TQ subscriptions
// ---------------------------------------------------------------------------

interface DAGCanvasProps {
  projectId: string;
  variant: 'pipeline' | 'documents';
  query: UseQueryResult<DAGResponse>;
  onTreeView?: () => void;
}

function DAGCanvas({ projectId, variant, query, onTreeView }: DAGCanvasProps) {
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

  // Searchable node list for DAGSearchBar
  const searchableNodes = useMemo<SearchableNode[]>(() => {
    if (!dagData) return [];
    return dagData.nodes.map((n) => ({
      id: n.id,
      label: n.data.label,
      componentKey: n.data.component_key,
      status: n.data.status,
      stageKey: n.data.stage_key,
      artifactType: n.data.artifact_type,
      hasArtifact: n.data.has_artifact,
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
  // Per-node height estimates, keyed by node id.
  const nodeHeights = useMemo(() => {
    const map = new Map<string, number>();
    for (const n of rawNodes) {
      map.set(n.id, estimateNodeHeight(n.data));
    }
    return map;
  }, [rawNodes]);

  // Topology key — stable primitive that only changes when node IDs, edge
  // connections, or node heights change. Pure status updates that don't affect
  // height skip the expensive dagre layout step.
  const topologyKey = useMemo(
    () =>
      rawNodes.map((n) => `${n.id}:${nodeHeights.get(n.id) ?? 100}`).join('\0') +
      '|' +
      rawEdges.map((e) => `${e.source}>${e.target}`).join('\0'),
    [rawNodes, rawEdges, nodeHeights],
  );

  // Positions — only re-runs when topology changes.
  const positions = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    if (rawNodes.length === 0) return map;
    try {
      const g = new dagre.graphlib.Graph();
      g.setDefaultEdgeLabel(() => ({}));
      g.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 80 });
      rawNodes.forEach((n) => {
        const h = nodeHeights.get(n.id) ?? 100;
        g.setNode(n.id, { width: 220, height: h });
      });
      rawEdges.forEach((e) => g.setEdge(e.source, e.target));
      dagre.layout(g);
      rawNodes.forEach((n) => {
        const pos = g.node(n.id);
        const h = nodeHeights.get(n.id) ?? 100;
        map.set(n.id, pos ? { x: pos.x - 110, y: pos.y - h / 2 } : { x: 0, y: 0 });
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
      const h = nodeHeights.get(n.id) ?? 100;
      const serialized = JSON.stringify(n.data) + '|' + projectId;
      const cached = nodeRefCache.current.get(n.id);
      if (cached && cached.serialized === serialized && cached.node.position === pos && cached.node.height === h) {
        return cached.node;
      }
      const node = {
        ...n,
        data: { ...n.data, projectId },
        position: pos,
        width: 220,
        height: h,
      };
      nodeRefCache.current.set(n.id, { serialized, node });
      return node;
    });
    if (sameElements(next, prevNodesRef.current)) return prevNodesRef.current;
    prevNodesRef.current = next;
    return next;
  }, [rawNodes, positions, projectId, nodeHeights]);

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
      <DAGSearchBar nodes={searchableNodes} variant={variant} />
      <div className="absolute top-2 right-2 z-10 flex flex-col gap-1">
        <button
          onClick={() => setShowMinimap((v) => !v)}
          className="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white text-xs rounded border border-gray-600"
          title={showMinimap ? 'Hide minimap' : 'Show minimap'}
        >
          {showMinimap ? 'Hide Map' : 'Show Map'}
        </button>
        {onTreeView && (
          <button
            onClick={onTreeView}
            className="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white text-xs rounded border border-gray-600"
            title="Switch to tree view"
          >
            Tree View
          </button>
        )}
      </div>
      {showMinimap && (
        <MiniMap
          className="!bg-gray-800"
          nodeColor={minimapNodeColor}
        />
      )}
    </ReactFlow>
  );
}
