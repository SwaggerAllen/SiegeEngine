import { useState, useCallback, useMemo } from 'react';
import { useDAGStore } from '../../store/dagStore';
import type { SearchableNode } from './PipelineDAG';

// Artifact types that live at system level (no component_key)
const SYSTEM_ARTIFACT_TYPES = new Set([
  'project_doc',
  'system_requirements',
  'system_architecture',
  'high_level_plan',
  'component_map',
]);

// Order for system-level docs
const SYSTEM_ORDER: Record<string, number> = {
  project_doc: 0,
  system_requirements: 1,
  system_architecture: 2,
  high_level_plan: 3,
  component_map: 4,
};

// Artifact types that belong directly to a component
const COMPONENT_ARTIFACT_TYPES = new Set([
  'component_requirements',
  'component_architecture',
  'component_plan',
  'sub_component_map',
]);

const COMPONENT_DOC_ORDER: Record<string, number> = {
  component_requirements: 0,
  component_architecture: 1,
  component_plan: 2,
  sub_component_map: 3,
};

const SUB_COMPONENT_DOC_ORDER: Record<string, number> = {
  sub_component_requirements: 0,
  sub_component_architecture: 1,
  sub_component_plan: 2,
  code: 3,
  code_review: 4,
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

interface TreeNode {
  type: 'document' | 'folder';
  label: string;
  node?: SearchableNode; // only for documents
  children?: TreeNode[]; // only for folders
  key: string;
}

function buildTree(nodes: SearchableNode[]): TreeNode[] {
  const tree: TreeNode[] = [];

  // 1. System-level docs
  const systemDocs = nodes
    .filter((n) => SYSTEM_ARTIFACT_TYPES.has(n.stageKey) || (!n.componentKey && SYSTEM_ARTIFACT_TYPES.has(getArtifactType(n))))
    .sort((a, b) => (SYSTEM_ORDER[getArtifactType(a)] ?? 99) - (SYSTEM_ORDER[getArtifactType(b)] ?? 99));

  for (const doc of systemDocs) {
    tree.push({ type: 'document', label: doc.label, node: doc, key: `doc-${doc.id}` });
  }

  // 2. Group remaining nodes by component
  const componentMap = new Map<string, SearchableNode[]>();
  const subComponentMap = new Map<string, Map<string, SearchableNode[]>>();

  for (const n of nodes) {
    if (!n.componentKey) continue;
    if (SYSTEM_ARTIFACT_TYPES.has(getArtifactType(n))) continue;

    // Check if this is a sub-component (component_key contains ".")
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
      // Sub-component level docs without dot notation — group by component_key
      // This handles cases where component_key is the sub-component directly
      if (!componentMap.has(n.componentKey)) componentMap.set(n.componentKey, []);
      componentMap.get(n.componentKey)!.push(n);
    }
  }

  // Collect all component keys (from both maps)
  const allComponentKeys = new Set([...componentMap.keys(), ...subComponentMap.keys()]);

  if (allComponentKeys.size > 0) {
    const componentChildren: TreeNode[] = [];

    for (const compKey of [...allComponentKeys].sort()) {
      const compDocs = (componentMap.get(compKey) ?? [])
        .sort((a, b) => (COMPONENT_DOC_ORDER[getArtifactType(a)] ?? 99) - (COMPONENT_DOC_ORDER[getArtifactType(b)] ?? 99));

      const compChildren: TreeNode[] = compDocs.map((d) => ({
        type: 'document' as const,
        label: d.label,
        node: d,
        key: `doc-${d.id}`,
      }));

      // Sub-components folder
      const subs = subComponentMap.get(compKey);
      if (subs && subs.size > 0) {
        const subFolders: TreeNode[] = [];
        for (const [subKey, subDocs] of [...subs.entries()].sort(([a], [b]) => a.localeCompare(b))) {
          const sortedSubDocs = subDocs.sort(
            (a, b) => (SUB_COMPONENT_DOC_ORDER[getArtifactType(a)] ?? 99) - (SUB_COMPONENT_DOC_ORDER[getArtifactType(b)] ?? 99),
          );
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

/** Derive artifact_type from the node's stageKey (they typically match). */
function getArtifactType(n: SearchableNode): string {
  return n.stageKey;
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
}: {
  node: TreeNode;
  depth: number;
  selected: boolean;
  onClick: () => void;
}) {
  const searchNode = node.node!;
  return (
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
      {searchNode.componentKey && (
        <span className="text-gray-600 text-xs ml-auto truncate max-w-[80px]">{searchNode.componentKey}</span>
      )}
    </button>
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
}: {
  nodes: TreeNode[];
  depth: number;
  expandedKeys: Set<string>;
  toggleKey: (key: string) => void;
  selectedArtifactId: string | null;
  onSelectArtifact: (id: string) => void;
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
              if (treeNode.node?.hasArtifact) {
                onSelectArtifact(treeNode.node.id);
              }
            }}
          />
        );
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export function DocumentTreeView({ nodes }: { nodes: SearchableNode[] }) {
  const selectArtifact = useDAGStore((s) => s.selectArtifact);
  const selectedArtifactId = useDAGStore((s) => s.selectedArtifactId);

  const tree = useMemo(() => buildTree(nodes), [nodes]);

  // Start with top-level folders expanded
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    initial.add('components-root');
    return initial;
  });

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
      selectArtifact(id);
    },
    [selectArtifact],
  );

  return (
    <div className="h-full flex flex-col bg-gray-900 overflow-hidden">
      <div className="flex-1 overflow-y-auto py-1">
        {tree.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-500 text-sm">
            No documents yet
          </div>
        ) : (
          <TreeBranch
            nodes={tree}
            depth={0}
            expandedKeys={expandedKeys}
            toggleKey={toggleKey}
            selectedArtifactId={selectedArtifactId}
            onSelectArtifact={onSelectArtifact}
          />
        )}
      </div>
    </div>
  );
}
