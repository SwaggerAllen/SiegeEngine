import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
// @ts-expect-error cytoscape-elk has no type declarations
import elk from 'cytoscape-elk';
import CytoscapeComponent from 'react-cytoscapejs';

import { useDAGStore } from '../../store/dagStore';
import { useDAGData, useDocumentsDAGData } from '../../hooks/queries/useDAGQueries';
import { DocumentTreeView } from './DocumentTreeView';
import { debugLog } from '../../lib/debugLog';
import { MAP_ARTIFACT_TYPES, type DAGResponse } from '../../types/dag';
import type { UseQueryResult } from '@tanstack/react-query';

// Register cytoscape-elk layout
elk(cytoscape);

// ── Phase assignment ───────────────────────────────────────────────────
// Maps artifact_type to a logical phase. Nodes in the same phase share a
// visual band. The actual ELK partition values are computed dynamically so
// that each phase starts at an offset past the previous phase's node count,
// preventing ELK from visually mixing adjacent phases.
const ARTIFACT_PHASE: Record<string, number> = {
  project_doc: 0,
  feature_expansion: 1,
  system_architecture: 2,
  component_map: 3,
  component_architecture: 4,
  sub_component_map: 5,
  component_plan: 6,
  sub_component_architecture: 7,
  sub_component_plan: 8,
  code: 9,
  code_review: 10,
  // Frontend DAG phases (re-numbered from 3 onward when viewing frontend)
  frontend_component_map: 3,
  frontend_component_architecture: 4,
  frontend_sub_component_map: 5,
  frontend_component_plan: 6,
  frontend_sub_component_architecture: 7,
  frontend_sub_component_plan: 8,
  frontend_code: 9,
  frontend_code_review: 10,
};

// ── Status → color mapping ──────────────────────────────────────────────
const STATUS_BG: Record<string, string> = {
  pending: '#374151',
  conditional: '#1f2937',
  running: '#1e4976',
  generating: '#1e4976',
  ai_reviewing: '#3b1f6e',
  awaiting_review: '#713f12',
  approved: '#14532d',
  rejected: '#7f1d1d',
  failed: '#7f1d1d',
};

const STATUS_BORDER: Record<string, string> = {
  pending: '#6b7280',
  conditional: '#4b5563',
  running: '#60a5fa',
  generating: '#60a5fa',
  ai_reviewing: '#a855f7',
  awaiting_review: '#eab308',
  approved: '#22c55e',
  rejected: '#ef4444',
  failed: '#ef4444',
};

const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  conditional: 'Conditional',
  running: 'Running...',
  generating: 'Generating...',
  ai_reviewing: 'AI Reviewing...',
  awaiting_review: 'Awaiting Review',
  approved: 'Approved',
  rejected: 'Rejected',
  failed: 'Failed',
};


// ── Searchable node type (shared with DocumentTreeView) ─────────────────
export interface SearchableNode {
  id: string;
  label: string;
  componentKey: string | null;
  status: string;
  isStale?: boolean;
  stageKey: string;
  artifactType: string;
  hasArtifact: boolean;
}

// ── Search bar ──────────────────────────────────────────────────────────
export function DAGSearchBar({
  nodes,
  variant,
  cyRef,
}: {
  nodes: SearchableNode[];
  variant: 'pipeline' | 'documents';
  cyRef: React.MutableRefObject<cytoscape.Core | null>;
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [highlightIdx, setHighlightIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const selectArtifact = useDAGStore((s) => s.selectArtifact);
  const selectStage = useDAGStore((s) => s.selectStage);

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

  useEffect(() => { setHighlightIdx(0); }, [matches.length]);

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
        if (node.hasArtifact) {
          selectArtifact(node.id);
        } else {
          selectStage(node.stageKey);
        }
      }
      // Pan to the selected node in Cytoscape
      const cy = cyRef.current;
      if (cy) {
        const cyNode = cy.getElementById(node.id);
        if (cyNode.length) {
          cy.animate({ center: { eles: cyNode }, zoom: 1.2 }, { duration: 300 });
        }
      }
      setOpen(false);
      setQuery('');
    },
    [variant, selectStage, selectArtifact, cyRef],
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
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
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

// ── Node tooltip overlay ────────────────────────────────────────────────
// Shows cancel/restart actions on hover via an HTML overlay positioned
// over the selected Cytoscape node.
function NodeTooltip({
  cyRef,
  selectedNodeId,
  projectId,
  variant,
}: {
  cyRef: React.MutableRefObject<cytoscape.Core | null>;
  selectedNodeId: string | null;
  projectId: string;
  variant: 'pipeline' | 'documents';
}) {
  // Tooltip is rendered by the parent for the currently-selected node.
  // For now it shows status info; cancel/restart live in the detail panel.
  // Keeping the interface for future expansion.
  void cyRef; void selectedNodeId; void projectId; void variant;
  return null;
}

// ── Cytoscape stylesheet ────────────────────────────────────────────────
function buildStylesheet() {
  return [
    // Default node style
    {
      selector: 'node',
      style: {
        label: 'data(label)',
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'wrap',
        'text-max-width': '200px',
        color: '#ffffff',
        'font-size': '12px',
        'font-family': 'ui-monospace, SFMono-Regular, Menlo, Monaco, monospace',
        width: 220,
        height: 60,
        shape: 'round-rectangle',
        'background-color': '#374151',
        'border-width': 2,
        'border-color': '#6b7280',
        padding: '10px',
        'text-outline-color': '#000000',
        'text-outline-width': 0,
      },
    },
    // Status-based node styles
    ...Object.entries(STATUS_BG).map(([status, bg]) => ({
      selector: `node[status = "${status}"]`,
      style: {
        'background-color': bg,
        'border-color': STATUS_BORDER[status] || '#6b7280',
      },
    })),
    // Branching nodes (component_map / sub_component_map)
    {
      selector: 'node[?isBranching]',
      style: {
        'background-color': '#312e81',
        'border-color': '#818cf8',
      },
    },
    // Input document (project_doc)
    {
      selector: 'node[?isInputDoc]',
      style: {
        'background-color': '#164e63',
        'border-color': '#22d3ee',
      },
    },
    // Placeholder nodes (generating, no artifact yet)
    {
      selector: 'node[?isPlaceholder]',
      style: {
        'border-style': 'dashed',
        'background-opacity': 0.6,
      },
    },
    // Conditional nodes
    {
      selector: 'node[status = "conditional"]',
      style: {
        'border-style': 'dashed',
      },
    },
    // Stale nodes
    {
      selector: 'node[?isStale]',
      style: {
        'border-width': 3,
        'border-color': '#fb923c',
      },
    },
    // Selected node
    {
      selector: 'node:selected',
      style: {
        'border-width': 3,
        'border-color': '#ffffff',
        'overlay-color': '#ffffff',
        'overlay-opacity': 0.1,
      },
    },
    // Default edge style
    {
      selector: 'edge',
      style: {
        width: 1.5,
        'line-color': '#4b5563',
        'target-arrow-color': '#4b5563',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'arrow-scale': 0.8,
      },
    },
    // Animated edges (active nodes)
    {
      selector: 'edge[?animated]',
      style: {
        'line-color': '#60a5fa',
        'target-arrow-color': '#60a5fa',
        'line-style': 'dashed',
        'line-dash-pattern': [6, 3],
      },
    },
    // Cross-component dependency edges (dashed indigo)
    {
      selector: 'edge[?isDependencyEdge]',
      style: {
        'line-style': 'dashed',
        'line-dash-pattern': [5, 5],
        'line-color': '#818cf8',
        'target-arrow-color': '#818cf8',
      },
    },
    // Intra-layer edges (same partition) — routed distinctly
    {
      selector: 'edge[?isIntraLayer]',
      style: {
        'curve-style': 'unbundled-bezier',
        'line-color': '#818cf8',
        'target-arrow-color': '#818cf8',
        'line-style': 'dashed',
        'line-dash-pattern': [5, 5],
        width: 1.5,
        'control-point-distances': [40],
        'control-point-weights': [0.5],
      },
    },
  ] as cytoscape.StylesheetStyle[];
}

// ── Build Cytoscape elements from DAG response ──────────────────────────
function buildElements(dagData: DAGResponse): cytoscape.ElementDefinition[] {
  const elements: cytoscape.ElementDefinition[] = [];

  // Count nodes per phase so we can space partitions apart
  const phaseCounts = new Map<number, number>();
  for (const n of dagData.nodes) {
    const phase = ARTIFACT_PHASE[n.data.artifact_type] ?? 99;
    phaseCounts.set(phase, (phaseCounts.get(phase) ?? 0) + 1);
  }

  // Compute partition offset for each phase: each phase starts after the
  // previous phase's node count + 1 gap, so ELK never merges adjacent phases.
  const sortedPhases = [...new Set(dagData.nodes.map((n) => ARTIFACT_PHASE[n.data.artifact_type] ?? 99))].sort((a, b) => a - b);
  const phasePartition = new Map<number, number>();
  let offset = 0;
  for (const phase of sortedPhases) {
    phasePartition.set(phase, offset);
    offset += (phaseCounts.get(phase) ?? 1) + 1;
  }

  // Build a lookup of node id → phase for intra-layer edge detection
  const nodeLayerMap = new Map<string, number>();

  for (const n of dagData.nodes) {
    const artifactType = n.data.artifact_type;
    const phase = ARTIFACT_PHASE[artifactType] ?? 99;
    const layer = phasePartition.get(phase) ?? 0;
    nodeLayerMap.set(n.id, phase);

    const isBranching = MAP_ARTIFACT_TYPES.has(artifactType);
    const isInputDoc = artifactType === 'project_doc';
    const isPlaceholder = !n.data.has_artifact && n.data.is_active;
    const componentKey = n.data.component_key;

    // Build multi-line label: component key on top, then artifact label, then status
    const parts: string[] = [];
    if (componentKey) parts.push(componentKey.replace(/_/g, ' '));
    parts.push(n.data.label);
    const statusLabel = isPlaceholder
      ? 'Generating...'
      : isInputDoc
        ? 'Input'
        : isBranching && n.data.status === 'pending'
          ? 'Branching'
          : (STATUS_LABELS[n.data.status] || (n.data.status ?? 'pending').replace('_', ' '));
    parts.push(statusLabel);

    elements.push({
      group: 'nodes',
      data: {
        id: n.id,
        label: parts.join('\n'),
        status: n.data.status,
        artifactType,
        componentKey,
        stageKey: n.data.stage_key,
        hasArtifact: n.data.has_artifact,
        isActive: n.data.is_active,
        isBranching,
        isInputDoc,
        isPlaceholder,
        isStale: n.data.is_stale ?? false,
        version: n.data.version,
        // ELK partition for layered layout
        elkPartition: layer,
      },
    });
  }

  for (const e of dagData.edges) {
    const srcLayer = nodeLayerMap.get(e.source);
    const tgtLayer = nodeLayerMap.get(e.target);
    const isIntraLayer = srcLayer !== undefined && tgtLayer !== undefined && srcLayer === tgtLayer;
    const isDependencyEdge = !!(e as Record<string, unknown>).style;

    elements.push({
      group: 'edges',
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        animated: e.animated,
        isDependencyEdge,
        isIntraLayer,
      },
    });
  }

  return elements;
}

// ── ELK layout options ──────────────────────────────────────────────────
function getElkLayoutOptions() {
  return {
    name: 'elk' as const,
    elk: {
      algorithm: 'layered',
      'elk.direction': 'DOWN',
      'elk.layered.spacing.nodeNodeBetweenLayers': '100',
      'elk.spacing.nodeNode': '60',
      'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
      'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
      'elk.partitioning.activate': 'true',
      'elk.layered.layering.strategy': 'INTERACTIVE',
    },
    // Map each node's partition from its data
    elkOverrides: (node: cytoscape.NodeSingular) => ({
      'elk.partitioning.partition': String(node.data('elkPartition') ?? 0),
      'elk.layered.layerConstraint': undefined,
    }),
  };
}

// ── Main component ──────────────────────────────────────────────────────
interface CytoscapeDAGProps {
  projectId: string;
  variant?: 'pipeline' | 'documents';
}

export function CytoscapeDAGView({ projectId, variant = 'pipeline' }: CytoscapeDAGProps) {
  if (variant === 'documents') {
    return <DocumentsDAGInner projectId={projectId} />;
  }
  return <WorkflowDAGInner projectId={projectId} />;
}

function WorkflowDAGInner({ projectId }: { projectId: string }) {
  const query = useDAGData(projectId);
  return <CytoscapeCanvas projectId={projectId} variant="pipeline" query={query} />;
}

function DocumentsDAGInner({ projectId }: { projectId: string }) {
  const [dagType, setDagType] = useState<'domain' | 'frontend'>('domain');
  const query = useDocumentsDAGData(projectId, dagType);
  const [viewMode, setViewMode] = useState<'dag' | 'tree'>('tree');

  const searchableNodes = useMemo<SearchableNode[]>(() => {
    if (!query.data) return [];
    return query.data.nodes.map((n) => ({
      id: n.id,
      label: n.data.label,
      componentKey: n.data.component_key,
      status: n.data.status,
      isStale: n.data.is_stale ?? false,
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

  const dagToggle = (
    <div className="flex bg-gray-800 rounded border border-gray-600 overflow-hidden">
      <button
        onClick={() => setDagType('domain')}
        className={`px-3 py-1 text-xs font-medium transition-colors ${
          dagType === 'domain'
            ? 'bg-blue-600 text-white'
            : 'text-gray-400 hover:text-white hover:bg-gray-700'
        }`}
      >
        Backend
      </button>
      <button
        onClick={() => setDagType('frontend')}
        className={`px-3 py-1 text-xs font-medium transition-colors ${
          dagType === 'frontend'
            ? 'bg-blue-600 text-white'
            : 'text-gray-400 hover:text-white hover:bg-gray-700'
        }`}
      >
        Frontend
      </button>
    </div>
  );

  if (viewMode === 'tree') {
    return (
      <div className="h-full relative">
        <DocumentTreeView nodes={searchableNodes} edges={query.data?.edges ?? []} projectId={projectId} headerExtra={dagToggle} />
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

  return <CytoscapeCanvas key={dagType} projectId={projectId} variant="documents" query={query} onTreeView={() => setViewMode('tree')} headerExtra={dagToggle} />;
}

// ── Canvas ──────────────────────────────────────────────────────────────
interface CytoscapeCanvasProps {
  projectId: string;
  variant: 'pipeline' | 'documents';
  query: UseQueryResult<DAGResponse>;
  onTreeView?: () => void;
  headerExtra?: React.ReactNode;
}

function CytoscapeCanvas({ projectId, variant, query, onTreeView, headerExtra }: CytoscapeCanvasProps) {
  const { data: dagData, isLoading, isError, error } = query;
  const cyRef = useRef<cytoscape.Core | null>(null);
  const selectArtifact = useDAGStore((s) => s.selectArtifact);
  const selectStage = useDAGStore((s) => s.selectStage);
  const clearSelection = useDAGStore((s) => s.clearSelection);
  const [layoutDone, setLayoutDone] = useState(false);
  const prevElementKeyRef = useRef<string>('');

  const elements = useMemo(() => {
    if (!dagData) return [];
    return buildElements(dagData);
  }, [dagData]);

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

  const stylesheet = useMemo(() => buildStylesheet(), []);

  // Detect topology changes (node/edge IDs) to know when to re-run layout
  const elementKey = useMemo(() => {
    const nodeIds = elements.filter((e) => e.group === 'nodes').map((e) => e.data.id).sort().join(',');
    const edgeIds = elements.filter((e) => e.group === 'edges').map((e) => `${e.data.source}>${e.data.target}`).sort().join(',');
    return `${nodeIds}|${edgeIds}`;
  }, [elements]);

  // Run ELK layout when topology changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || elements.length === 0) return;
    if (elementKey === prevElementKeyRef.current) return;
    prevElementKeyRef.current = elementKey;

    setLayoutDone(false);
    const layout = cy.layout(getElkLayoutOptions() as unknown as cytoscape.LayoutOptions);
    layout.on('layoutstop', () => {
      setLayoutDone(true);
      cy.fit(undefined, 40);
    });
    layout.run();

    return () => { layout.stop(); };
  }, [elementKey, elements.length]);

  // Click handlers
  const handleCySetup = useCallback(
    (cy: cytoscape.Core) => {
      cyRef.current = cy;

      cy.on('tap', 'node', (evt) => {
        const node = evt.target;
        if (variant === 'pipeline') {
          selectStage(node.data('stageKey') ?? null);
        } else {
          if (node.data('hasArtifact')) {
            selectArtifact(node.id());
          } else {
            // Pending/conditional nodes: open the stage panel so the user
            // can trigger the first generation via "Run Stage".
            selectStage(node.data('stageKey') ?? null);
          }
        }
      });

      cy.on('tap', (evt) => {
        if (evt.target === cy) {
          clearSelection();
        }
      });
    },
    [variant, selectStage, selectArtifact, clearSelection],
  );

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const handler = (evt: cytoscape.EventObject) => {
      setSelectedNodeId(evt.target.id());
    };
    const clearHandler = (evt: cytoscape.EventObject) => {
      if (evt.target === cy) setSelectedNodeId(null);
    };
    cy.on('tap', 'node', handler);
    cy.on('tap', clearHandler);
    return () => {
      cy.off('tap', 'node', handler);
      cy.off('tap', clearHandler);
    };
  }, []);

  if (isError) {
    return (
      <div className="flex items-center justify-center h-full text-red-400">
        Failed to load {variant === 'documents' ? 'documents' : 'pipeline'}: {String(error)}
      </div>
    );
  }

  if (!dagData || elements.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        {isLoading
          ? (variant === 'documents' ? 'Loading documents...' : 'Loading pipeline stages...')
          : (variant === 'documents' ? 'No documents yet' : 'No pipeline stages yet')}
      </div>
    );
  }

  return (
    <div className="h-full w-full relative bg-gray-900">
      <CytoscapeComponent
        elements={elements}
        stylesheet={stylesheet as cytoscape.StylesheetStyle[]}
        cy={handleCySetup}
        style={{ width: '100%', height: '100%' }}
        minZoom={0.1}
        maxZoom={3}
        wheelSensitivity={0.3}
        boxSelectionEnabled={false}
        autoungrabify={true}
      />
      {!layoutDone && elements.length > 0 && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-900/80 z-20">
          <span className="text-gray-400 text-sm">Computing layout...</span>
        </div>
      )}
      {headerExtra && (
        <div className="absolute top-14 left-2 z-20">{headerExtra}</div>
      )}
      <DAGSearchBar nodes={searchableNodes} variant={variant} cyRef={cyRef} />
      <div className="absolute top-2 right-2 z-10 flex flex-col gap-1">
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
      <NodeTooltip cyRef={cyRef} selectedNodeId={selectedNodeId} projectId={projectId} variant={variant} />
    </div>
  );
}
