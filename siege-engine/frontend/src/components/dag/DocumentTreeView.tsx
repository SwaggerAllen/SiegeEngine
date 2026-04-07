import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { useDAGStore } from '../../store/dagStore';
import type { SearchableNode } from './PipelineDAG';

// ── Edge type (matches DAGResponse.edges) ────────────────────────────────
export interface DAGEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  animated: boolean;
}

// Artifact types that live at system level (no component_key)
const SYSTEM_ARTIFACT_TYPES = new Set([
  'project_doc',
  'feature_expansion',
  'system_requirements',
  'system_architecture',
  'high_level_plan',
  'component_map',
  'frontend_component_map',
]);

// Order for system-level docs
const SYSTEM_ORDER: Record<string, number> = {
  project_doc: 0,
  feature_expansion: 1,
  system_requirements: 2,
  system_architecture: 3,
  high_level_plan: 4,
  component_map: 5,
  frontend_component_map: 6,
};

// Artifact types that belong directly to a component
const COMPONENT_ARTIFACT_TYPES = new Set([
  'component_requirements',
  'component_architecture',
  'component_plan',
  'sub_component_map',
  // Frontend DAG
  'frontend_component_architecture',
  'frontend_component_plan',
  'frontend_sub_component_map',
]);

const COMPONENT_DOC_ORDER: Record<string, number> = {
  component_requirements: 0,
  component_architecture: 1,
  component_plan: 2,
  sub_component_map: 3,
  // Frontend DAG (same ordering within component)
  frontend_component_architecture: 1,
  frontend_component_plan: 2,
  frontend_sub_component_map: 3,
};

const SUB_COMPONENT_DOC_ORDER: Record<string, number> = {
  sub_component_requirements: 0,
  sub_component_architecture: 1,
  sub_component_plan: 2,
  code: 3,
  code_review: 4,
  // Frontend DAG
  frontend_sub_component_architecture: 1,
  frontend_sub_component_plan: 2,
  frontend_code: 3,
  frontend_code_review: 4,
};

const STATUS_DOTS: Record<string, string> = {
  approved: 'bg-green-500',
  awaiting_review: 'bg-yellow-500',
  generating: 'bg-blue-500 animate-pulse',
  running: 'bg-blue-500 animate-pulse',
  ai_reviewing: 'bg-purple-500 animate-pulse',
  rejected: 'bg-red-500',
  failed: 'bg-red-700',
  pending: 'bg-gray-500',
  conditional: 'bg-gray-600',
};

const ACTIVE_STATUSES = new Set(['running', 'generating', 'ai_reviewing']);

interface TreeNode {
  type: 'document' | 'folder';
  label: string;
  node?: SearchableNode; // only for documents
  children?: TreeNode[]; // only for folders
  key: string;
}

// ── Dependency maps ──────────────────────────────────────────────────────

interface DepMaps {
  /** nodeId → list of node IDs that are direct dependencies (inputs) */
  dependencies: Map<string, string[]>;
  /** nodeId → list of node IDs that directly depend on this node */
  dependents: Map<string, string[]>;
}

function buildDepMaps(edges: DAGEdge[]): DepMaps {
  const dependencies = new Map<string, string[]>();
  const dependents = new Map<string, string[]>();
  for (const e of edges) {
    if (!dependencies.has(e.target)) dependencies.set(e.target, []);
    dependencies.get(e.target)!.push(e.source);
    if (!dependents.has(e.source)) dependents.set(e.source, []);
    dependents.get(e.source)!.push(e.target);
  }
  return { dependencies, dependents };
}

// ── Topological sort for dependency ordering ─────────────────────────────

function topoSort(nodeIds: string[], edges: DAGEdge[]): Map<string, number> {
  const idSet = new Set(nodeIds);
  const inDeg = new Map<string, number>();
  const adj = new Map<string, string[]>();
  for (const id of nodeIds) {
    inDeg.set(id, 0);
    adj.set(id, []);
  }
  for (const e of edges) {
    if (!idSet.has(e.source) || !idSet.has(e.target)) continue;
    adj.get(e.source)!.push(e.target);
    inDeg.set(e.target, (inDeg.get(e.target) ?? 0) + 1);
  }
  const queue: string[] = [];
  for (const [id, deg] of inDeg) {
    if (deg === 0) queue.push(id);
  }
  const order = new Map<string, number>();
  let idx = 0;
  while (queue.length > 0) {
    const cur = queue.shift()!;
    order.set(cur, idx++);
    for (const next of adj.get(cur) ?? []) {
      const newDeg = (inDeg.get(next) ?? 1) - 1;
      inDeg.set(next, newDeg);
      if (newDeg === 0) queue.push(next);
    }
  }
  // Nodes not reached (cycles) get a high order
  for (const id of nodeIds) {
    if (!order.has(id)) order.set(id, idx++);
  }
  return order;
}

// ── Tree builder ─────────────────────────────────────────────────────────

function buildTree(nodes: SearchableNode[], edges: DAGEdge[]): TreeNode[] {
  const topoOrder = topoSort(nodes.map((n) => n.id), edges);
  const depSort = (a: SearchableNode, b: SearchableNode) =>
    (topoOrder.get(a.id) ?? 999) - (topoOrder.get(b.id) ?? 999);

  const tree: TreeNode[] = [];

  // 1. System-level docs — sorted by dependency order
  const systemDocs = nodes
    .filter((n) => SYSTEM_ARTIFACT_TYPES.has(getArtifactType(n)))
    .sort((a, b) => {
      const oa = SYSTEM_ORDER[getArtifactType(a)] ?? 99;
      const ob = SYSTEM_ORDER[getArtifactType(b)] ?? 99;
      if (oa !== ob) return oa - ob;
      return depSort(a, b);
    });

  for (const doc of systemDocs) {
    tree.push({ type: 'document', label: doc.label, node: doc, key: `doc-${doc.id}` });
  }

  // 2. Group remaining nodes by component
  const componentMap = new Map<string, SearchableNode[]>();
  const subComponentMap = new Map<string, Map<string, SearchableNode[]>>();

  for (const n of nodes) {
    if (!n.componentKey) continue;
    if (SYSTEM_ARTIFACT_TYPES.has(getArtifactType(n))) continue;

    const dotIdx = n.componentKey.indexOf('.');
    if (dotIdx !== -1) {
      const parentKey = n.componentKey.substring(0, dotIdx);
      const subKey = n.componentKey;
      if (!subComponentMap.has(parentKey)) subComponentMap.set(parentKey, new Map());
      const subs = subComponentMap.get(parentKey)!;
      if (!subs.has(subKey)) subs.set(subKey, []);
      subs.get(subKey)!.push(n);
    } else if (COMPONENT_ARTIFACT_TYPES.has(getArtifactType(n))) {
      if (!componentMap.has(n.componentKey)) componentMap.set(n.componentKey, []);
      componentMap.get(n.componentKey)!.push(n);
    } else {
      if (!componentMap.has(n.componentKey)) componentMap.set(n.componentKey, []);
      componentMap.get(n.componentKey)!.push(n);
    }
  }

  // Sort components by earliest dependency order of their nodes
  const allComponentKeys = [...new Set([...componentMap.keys(), ...subComponentMap.keys()])];
  const compMinOrder = (key: string): number => {
    const docs = componentMap.get(key) ?? [];
    const subDocs = [...(subComponentMap.get(key)?.values() ?? [])].flat();
    const all = [...docs, ...subDocs];
    if (all.length === 0) return 999;
    return Math.min(...all.map((n) => topoOrder.get(n.id) ?? 999));
  };
  allComponentKeys.sort((a, b) => compMinOrder(a) - compMinOrder(b) || a.localeCompare(b));

  if (allComponentKeys.length > 0) {
    const componentChildren: TreeNode[] = [];

    for (const compKey of allComponentKeys) {
      const compDocs = (componentMap.get(compKey) ?? [])
        .sort((a, b) => {
          const oa = COMPONENT_DOC_ORDER[getArtifactType(a)] ?? 99;
          const ob = COMPONENT_DOC_ORDER[getArtifactType(b)] ?? 99;
          if (oa !== ob) return oa - ob;
          return depSort(a, b);
        });

      const compChildren: TreeNode[] = compDocs.map((d) => ({
        type: 'document' as const,
        label: d.label,
        node: d,
        key: `doc-${d.id}`,
      }));

      // Sub-components folder
      const subs = subComponentMap.get(compKey);
      if (subs && subs.size > 0) {
        const subEntries = [...subs.entries()];
        // Sort sub-components by earliest dependency order
        subEntries.sort(([, aDocs], [, bDocs]) => {
          const aMin = Math.min(...aDocs.map((n) => topoOrder.get(n.id) ?? 999));
          const bMin = Math.min(...bDocs.map((n) => topoOrder.get(n.id) ?? 999));
          return aMin - bMin;
        });

        const subFolders: TreeNode[] = [];
        for (const [subKey, subDocs] of subEntries) {
          const sortedSubDocs = subDocs.sort((a, b) => {
            const oa = SUB_COMPONENT_DOC_ORDER[getArtifactType(a)] ?? 99;
            const ob = SUB_COMPONENT_DOC_ORDER[getArtifactType(b)] ?? 99;
            if (oa !== ob) return oa - ob;
            return depSort(a, b);
          });
          const subLabel = subKey.includes('.') ? subKey.split('.').slice(1).join('.') : subKey;
          subFolders.push({
            type: 'folder',
            label: subLabel,
            children: sortedSubDocs.map((d) => ({
              type: 'document' as const,
              label: d.label,
              node: d,
              key: `doc-${d.id}`,
            })),
            key: `sub-${subKey}`,
          });
        }
        compChildren.push({
          type: 'folder',
          label: 'Sub-components',
          children: subFolders,
          key: `subs-${compKey}`,
        });
      }

      componentChildren.push({
        type: 'folder',
        label: compKey,
        children: compChildren,
        key: `comp-${compKey}`,
      });
    }

    tree.push({
      type: 'folder',
      label: 'Components',
      children: componentChildren,
      key: 'components-root',
    });
  }

  return tree;
}

/** Return the artifact type for tree classification. */
function getArtifactType(n: SearchableNode): string {
  return n.artifactType;
}

/**
 * Filter a tree to only include documents matching `query` and the ancestor
 * folders needed to reach them. Returns [filteredTree, keysToExpand].
 */
function filterTree(
  tree: TreeNode[],
  query: string,
): [TreeNode[], Set<string>] {
  const q = query.toLowerCase();
  const keysToExpand = new Set<string>();

  function walk(nodes: TreeNode[]): TreeNode[] {
    const result: TreeNode[] = [];
    for (const treeNode of nodes) {
      if (treeNode.type === 'document') {
        const n = treeNode.node!;
        const matches =
          n.label.toLowerCase().includes(q) ||
          (n.componentKey && n.componentKey.toLowerCase().includes(q)) ||
          n.status.toLowerCase().includes(q) ||
          n.stageKey.replace(/_/g, ' ').toLowerCase().includes(q);
        if (matches) result.push(treeNode);
      } else {
        // Folder: recurse, keep if any children survive
        const filteredChildren = walk(treeNode.children ?? []);
        if (filteredChildren.length > 0) {
          keysToExpand.add(treeNode.key);
          result.push({ ...treeNode, children: filteredChildren });
        }
      }
    }
    return result;
  }

  const filtered = walk(tree);
  return [filtered, keysToExpand];
}

// ---------------------------------------------------------------------------
// Dependency/Dependents pill list
// ---------------------------------------------------------------------------

function DepList({
  label,
  nodeIds,
  nodeMap,
  onSelect,
}: {
  label: string;
  nodeIds: string[];
  nodeMap: Map<string, SearchableNode>;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (nodeIds.length === 0) return null;

  return (
    <div className="ml-10 mb-0.5">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        className="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1"
      >
        <span className="w-3 text-center transition-transform duration-150"
          style={{ transform: open ? 'rotate(90deg)' : undefined, fontSize: '8px' }}
        >▶</span>
        {label} ({nodeIds.length})
      </button>
      {open && (
        <div className="ml-4 mt-0.5 space-y-px">
          {nodeIds.map((depId) => {
            const dep = nodeMap.get(depId);
            if (!dep) return null;
            return (
              <button
                key={depId}
                onClick={(e) => { e.stopPropagation(); onSelect(depId); }}
                className="flex items-center gap-1.5 px-1 py-0.5 text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-700/50 rounded w-full text-left"
              >
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${STATUS_DOTS[dep.status] ?? 'bg-gray-500'}`} />
                <span className="truncate">{dep.label}</span>
                {dep.componentKey && (
                  <span className="text-gray-600 text-[10px] ml-auto truncate max-w-[60px]">{dep.componentKey}</span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Folder row
// ---------------------------------------------------------------------------

function FolderRow({
  node,
  depth,
  expanded,
  onToggle,
}: {
  node: TreeNode;
  depth: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className="w-full flex items-center gap-1.5 px-2 py-1.5 text-sm text-left hover:bg-gray-700/50 group"
      style={{ paddingLeft: `${depth * 16 + 8}px` }}
    >
      <span className="text-gray-500 text-xs w-4 shrink-0 text-center transition-transform duration-150"
        style={{ transform: expanded ? 'rotate(90deg)' : undefined }}
      >
        ▶
      </span>
      <span className="text-yellow-500/80 shrink-0">
        {expanded ? '📂' : '📁'}
      </span>
      <span className="text-gray-200 truncate">{node.label}</span>
      {node.children && (
        <span className="text-gray-600 text-xs ml-auto shrink-0">{node.children.length}</span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Document row
// ---------------------------------------------------------------------------

function DocumentRow({
  node,
  depth,
  selected,
  onClick,
  depMaps,
  nodeMap,
  onSelectDep,
}: {
  node: TreeNode;
  depth: number;
  selected: boolean;
  onClick: () => void;
  depMaps: DepMaps;
  nodeMap: Map<string, SearchableNode>;
  onSelectDep: (id: string) => void;
}) {
  const searchNode = node.node!;
  const deps = depMaps.dependencies.get(searchNode.id) ?? [];
  const dependents = depMaps.dependents.get(searchNode.id) ?? [];

  return (
    <div>
      <button
        onClick={onClick}
        className={`w-full flex items-center gap-1.5 px-2 py-1.5 text-sm text-left ${
          selected
            ? 'bg-blue-900/40 text-white'
            : 'hover:bg-gray-700/50 text-gray-300'
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <span className="w-4 shrink-0" /> {/* spacer to align with folder arrows */}
        <span className={`w-2 h-2 rounded-full shrink-0 ${STATUS_DOTS[searchNode.status] ?? 'bg-gray-500'}`} />
        <span className="truncate">{node.label}</span>
        {ACTIVE_STATUSES.has(searchNode.status) && (
          <span className="px-1 py-0.5 text-[10px] bg-blue-600 text-white rounded shrink-0">
            {searchNode.status === 'ai_reviewing' ? 'reviewing' : 'generating'}
          </span>
        )}
        {searchNode.isStale && (
          <span className="px-1 py-0.5 text-[10px] bg-orange-600 text-white rounded shrink-0" title="Upstream inputs have changed">
            stale
          </span>
        )}
        {searchNode.componentKey && (
          <span className="text-gray-600 text-xs ml-auto truncate max-w-[80px]">{searchNode.componentKey}</span>
        )}
      </button>
      {deps.length > 0 && (
        <DepList label="Dependencies" nodeIds={deps} nodeMap={nodeMap} onSelect={onSelectDep} />
      )}
      {dependents.length > 0 && (
        <DepList label="Dependents" nodeIds={dependents} nodeMap={nodeMap} onSelect={onSelectDep} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tree renderer (recursive)
// ---------------------------------------------------------------------------

function TreeBranch({
  nodes,
  depth,
  expandedKeys,
  toggleKey,
  selectedArtifactId,
  onSelectArtifact,
  depMaps,
  nodeMap,
}: {
  nodes: TreeNode[];
  depth: number;
  expandedKeys: Set<string>;
  toggleKey: (key: string) => void;
  selectedArtifactId: string | null;
  onSelectArtifact: (id: string) => void;
  depMaps: DepMaps;
  nodeMap: Map<string, SearchableNode>;
}) {
  return (
    <>
      {nodes.map((treeNode) => {
        if (treeNode.type === 'folder') {
          const expanded = expandedKeys.has(treeNode.key);
          return (
            <div key={treeNode.key}>
              <FolderRow
                node={treeNode}
                depth={depth}
                expanded={expanded}
                onToggle={() => toggleKey(treeNode.key)}
              />
              {expanded && treeNode.children && (
                <TreeBranch
                  nodes={treeNode.children}
                  depth={depth + 1}
                  expandedKeys={expandedKeys}
                  toggleKey={toggleKey}
                  selectedArtifactId={selectedArtifactId}
                  onSelectArtifact={onSelectArtifact}
                  depMaps={depMaps}
                  nodeMap={nodeMap}
                />
              )}
            </div>
          );
        }
        return (
          <DocumentRow
            key={treeNode.key}
            node={treeNode}
            depth={depth}
            selected={treeNode.node?.id === selectedArtifactId}
            onClick={() => {
              if (treeNode.node) {
                onSelectArtifact(treeNode.node.id);
              }
            }}
            depMaps={depMaps}
            nodeMap={nodeMap}
            onSelectDep={onSelectArtifact}
          />
        );
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// localStorage persistence for expanded folders
// ---------------------------------------------------------------------------

function storageKey(projectId: string): string {
  return `siege-tree-expanded-keys:${projectId}`;
}

function loadExpandedKeys(projectId: string): Set<string> {
  try {
    const stored = localStorage.getItem(storageKey(projectId));
    if (stored) {
      const arr = JSON.parse(stored);
      if (Array.isArray(arr)) return new Set(arr);
    }
  } catch { /* ignore corrupt data */ }
  // Default: components root expanded
  return new Set(['components-root']);
}

function saveExpandedKeys(projectId: string, keys: Set<string>) {
  try {
    localStorage.setItem(storageKey(projectId), JSON.stringify([...keys]));
  } catch { /* ignore quota errors */ }
}

// ---------------------------------------------------------------------------
// Collect folder keys that contain actively generating nodes
// ---------------------------------------------------------------------------

function getActiveAncestorKeys(tree: TreeNode[]): Set<string> {
  const keys = new Set<string>();

  function walk(nodes: TreeNode[]): boolean {
    let hasActive = false;
    for (const node of nodes) {
      if (node.type === 'document') {
        if (node.node && ACTIVE_STATUSES.has(node.node.status)) {
          hasActive = true;
        }
      } else if (node.children) {
        if (walk(node.children)) {
          keys.add(node.key);
          hasActive = true;
        }
      }
    }
    return hasActive;
  }

  walk(tree);
  return keys;
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export function DocumentTreeView({
  nodes,
  edges = [],
  projectId = '',
  headerExtra,
}: {
  nodes: SearchableNode[];
  edges?: DAGEdge[];
  projectId?: string;
  headerExtra?: React.ReactNode;
}) {
  const selectArtifact = useDAGStore((s) => s.selectArtifact);
  const selectStage = useDAGStore((s) => s.selectStage);
  const selectedArtifactId = useDAGStore((s) => s.selectedArtifactId);
  const inputRef = useRef<HTMLInputElement>(null);

  const depMaps = useMemo(() => buildDepMaps(edges), [edges]);
  const nodeMap = useMemo(() => {
    const m = new Map<string, SearchableNode>();
    for (const n of nodes) m.set(n.id, n);
    return m;
  }, [nodes]);

  const tree = useMemo(() => buildTree(nodes, edges), [nodes, edges]);

  const [searchQuery, setSearchQuery] = useState('');

  // Filter tree and compute which folders to force-expand
  const [displayTree, searchExpandedKeys] = useMemo(() => {
    if (!searchQuery.trim()) return [tree, null] as const;
    return filterTree(tree, searchQuery);
  }, [tree, searchQuery]);

  // Count matching docs for the results badge
  const matchCount = useMemo(() => {
    if (!searchQuery.trim()) return 0;
    function countDocs(nodes: TreeNode[]): number {
      let count = 0;
      for (const n of nodes) {
        if (n.type === 'document') count++;
        else if (n.children) count += countDocs(n.children);
      }
      return count;
    }
    return countDocs(displayTree);
  }, [displayTree, searchQuery]);

  // Load persisted expanded keys from localStorage, keyed by project
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(() => loadExpandedKeys(projectId));

  // Re-load when project changes
  useEffect(() => {
    setExpandedKeys(loadExpandedKeys(projectId));
  }, [projectId]);

  // Persist to localStorage whenever expandedKeys changes
  useEffect(() => {
    saveExpandedKeys(projectId, expandedKeys);
  }, [projectId, expandedKeys]);

  // Auto-expand folders containing actively generating nodes
  const activeAncestorKeys = useMemo(() => getActiveAncestorKeys(tree), [tree]);

  // Track which keys we've already auto-expanded so we don't fight the user
  const prevAutoExpanded = useRef<Set<string>>(new Set());

  useEffect(() => {
    // Find newly-active folders that weren't active on the previous render
    const newKeys = new Set<string>();
    for (const key of activeAncestorKeys) {
      if (!prevAutoExpanded.current.has(key)) {
        newKeys.add(key);
      }
    }
    prevAutoExpanded.current = activeAncestorKeys;

    if (newKeys.size > 0) {
      setExpandedKeys((prev) => {
        const next = new Set(prev);
        for (const key of newKeys) next.add(key);
        return next;
      });
    }
  }, [activeAncestorKeys]);

  // When searching, force-expand ancestor folders of matches.
  // When not searching, use manual expandedKeys.
  const effectiveExpandedKeys = searchExpandedKeys ?? expandedKeys;

  const toggleKey = useCallback((key: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const onSelectArtifact = useCallback(
    (id: string) => {
      const node = nodeMap.get(id);
      if (node?.hasArtifact) {
        selectArtifact(id);
      } else if (node) {
        selectStage(node.stageKey);
      }
    },
    [selectArtifact, selectStage, nodeMap],
  );

  // Keyboard shortcut: focus search on Ctrl/Cmd+F when tree is visible
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
        // Only capture if tree view is in the DOM
        if (inputRef.current) {
          e.preventDefault();
          inputRef.current.focus();
        }
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  return (
    <div className="h-full flex flex-col bg-gray-900 overflow-hidden">
      {/* DAG type toggle + Search bar */}
      <div className="px-2 pt-2 pb-1 border-b border-gray-800">
        {headerExtra && <div className="mb-2">{headerExtra}</div>}
      </div>
      <div className="px-2 pt-1 pb-1 border-b border-gray-800">
        <div className="relative">
          <input
            ref={inputRef}
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setSearchQuery('');
                inputRef.current?.blur();
              }
            }}
            placeholder="Filter documents..."
            className="w-full px-3 py-1.5 bg-gray-800 text-white text-sm rounded border border-gray-700 focus:border-blue-500 focus:outline-none placeholder-gray-500"
          />
          {searchQuery ? (
            <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center gap-1">
              <span className="text-xs text-gray-500">
                {matchCount} {matchCount === 1 ? 'match' : 'matches'}
              </span>
              <button
                onClick={() => { setSearchQuery(''); inputRef.current?.focus(); }}
                className="text-gray-500 hover:text-gray-300 text-sm px-1"
              >
                ✕
              </button>
            </div>
          ) : null}
        </div>
      </div>

      {/* Tree */}
      <div className="flex-1 overflow-y-auto py-1 pb-64">
        {tree.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-500 text-sm">
            No documents yet
          </div>
        ) : displayTree.length === 0 && searchQuery.trim() ? (
          <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
            No matching documents
          </div>
        ) : (
          <TreeBranch
            nodes={displayTree}
            depth={0}
            expandedKeys={effectiveExpandedKeys}
            toggleKey={toggleKey}
            selectedArtifactId={selectedArtifactId}
            onSelectArtifact={onSelectArtifact}
            depMaps={depMaps}
            nodeMap={nodeMap}
          />
        )}
      </div>
    </div>
  );
}
