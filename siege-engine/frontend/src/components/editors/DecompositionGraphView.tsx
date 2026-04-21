import { useCallback, useMemo, useState } from 'react';
import type { ElementDefinition } from 'cytoscape';
import { mintClientId, type Instruction } from '../../api/queue';
import type { StructureNode } from '../../api/structure';
import { useEnqueueInstructionMutation } from '../../hooks/mutations/useQueueMutations';
import { fullDagStylesheet } from '../graph/stylesheet';
import { EditableGraph } from './graph/EditableGraph';
import { editStylesheet } from './graph/editStylesheet';
import {
  NodeActionSidebar,
  SidebarActionButton,
} from './graph/NodeActionSidebar';
import { useEditableGraphSelection } from './graph/useEditableGraphSelection';

/**
 * Cytoscape-driven decomposition editor (UI #3 per v2-roadmap §Phase 11).
 *
 * Tree layout: all comp_* nodes (top + sub), synthetic parent→child
 * edges derived from ``parent_id`` (dashed styling to distinguish
 * from dependency / domain-parent edges).
 *
 * No two-tap edge-add path — decomposition edges are implicit from
 * the tree structure. Instead, tapping a comp opens the
 * ``NodeActionSidebar`` with per-node actions: Create child,
 * Rename, Delete, Move under…. Multi-select (for Merge in PR-11b)
 * lands next.
 */

interface Props {
  projectId: string;
  allComps: StructureNode[];
}

export function DecompositionGraphView({ projectId, allComps }: Props) {
  const enqueue = useEnqueueInstructionMutation(projectId);
  const [activeModal, setActiveModal] = useState<
    | null
    | { kind: 'create-top'; initialName: string }
    | { kind: 'create-child'; parent: StructureNode; initialName: string }
    | { kind: 'rename'; node: StructureNode; initialName: string }
    | { kind: 'move'; node: StructureNode }
  >(null);

  const compById = useMemo(() => {
    const m = new Map<string, StructureNode>();
    for (const c of allComps) m.set(c.id, c);
    return m;
  }, [allComps]);

  const elements = useMemo<ElementDefinition[]>(() => {
    const nodeEls = allComps.map((c) => ({
      data: {
        id: c.id,
        name: c.name,
        type:
          c.parent_id === null
            ? c.kind === 'presentational'
              ? 'comp-top-pres'
              : 'comp-top'
            : 'comp-sub',
      },
    }));
    const edgeEls: ElementDefinition[] = [];
    for (const c of allComps) {
      if (c.parent_id) {
        edgeEls.push({
          data: {
            id: `parent_${c.id}`,
            source: c.parent_id,
            target: c.id,
            type: 'parent',
          },
          classes: 'parent-edge',
        });
      }
    }
    return [...nodeEls, ...edgeEls];
  }, [allComps]);

  // Decomposition has no edge-staging path; canConnect always
  // returns false so the selection hook never transitions to
  // edge-staged. Node taps stay in source-selected for the
  // sidebar to pick up.
  const selection = useEditableGraphSelection({ canConnect: () => false });

  const stylesheet = useMemo(
    () => [
      ...fullDagStylesheet,
      ...editStylesheet,
      {
        selector: 'edge.parent-edge',
        css: {
          'line-style': 'dashed',
          'line-color': '#4b5563',
          'target-arrow-color': '#4b5563',
          width: 1,
        },
      },
    ],
    [],
  );

  const isDescendant = useCallback(
    (ancestorId: string, candidateId: string): boolean => {
      let cur = compById.get(candidateId);
      while (cur && cur.parent_id) {
        if (cur.parent_id === ancestorId) return true;
        cur = compById.get(cur.parent_id);
      }
      return false;
    },
    [compById],
  );

  const validMoveTargets = useCallback(
    (node: StructureNode) => {
      const out: Array<{ id: string | null; name: string }> = [
        { id: null, name: '(top-level)' },
      ];
      for (const c of allComps) {
        if (c.id === node.id) continue;
        if (c.parent_id === node.id) continue;
        if (isDescendant(node.id, c.id)) continue;
        if (c.id === node.parent_id) continue;
        out.push({ id: c.id, name: c.name });
      }
      return out;
    },
    [allComps, isDescendant],
  );

  const sidebar = (() => {
    if (selection.state.kind !== 'source-selected') return null;
    const node = compById.get(selection.state.sourceId);
    if (!node) return null;
    return (
      <NodeActionSidebar
        title={node.name}
        subtitle={node.parent_id === null ? 'Top-level comp' : 'Subcomp'}
        onCancel={selection.cancel}
        actions={
          <div className="space-y-1.5">
            <SidebarActionButton
              label="Create child…"
              variant="primary"
              testId="decomp-action-create-child"
              onClick={() => {
                setActiveModal({
                  kind: 'create-child',
                  parent: node,
                  initialName: '',
                });
              }}
            />
            <SidebarActionButton
              label="Rename…"
              testId="decomp-action-rename"
              onClick={() =>
                setActiveModal({ kind: 'rename', node, initialName: node.name })
              }
            />
            <SidebarActionButton
              label="Move under…"
              testId="decomp-action-move"
              onClick={() => setActiveModal({ kind: 'move', node })}
            />
            <SidebarActionButton
              label="Delete"
              variant="destructive"
              testId="decomp-action-delete"
              onClick={() => {
                if (!confirm(`Delete "${node.name}"? This halts downstream regens.`)) return;
                const ins: Instruction = {
                  instruction_type: 'Delete',
                  node_id: node.id,
                  name: node.name,
                };
                enqueue.mutate(ins, { onSuccess: selection.commit });
              }}
            />
          </div>
        }
      />
    );
  })();

  return (
    <div className="flex h-full min-h-[500px]" data-testid="decomposition-graph-view">
      <div className="flex flex-col flex-1 min-w-0 min-h-0">
        <div className="flex items-center gap-2 border-b border-gray-800 px-3 py-1.5 text-xs">
          <button
            type="button"
            onClick={() =>
              setActiveModal({ kind: 'create-top', initialName: '' })
            }
            className="rounded bg-blue-700 px-2 py-0.5 text-white hover:bg-blue-600"
            data-testid="decomp-create-top"
          >
            + New top-level comp
          </button>
          <span className="text-gray-500">
            Tap a comp to open actions.
          </span>
        </div>
        <div className="flex-1 min-h-0">
          {allComps.length === 0 ? (
            <EmptyState
              onCreate={() => setActiveModal({ kind: 'create-top', initialName: '' })}
            />
          ) : (
            <EditableGraph
              elements={elements}
              stylesheet={stylesheet}
              selection={selection}
              layoutKey={String(allComps.length)}
            />
          )}
        </div>
      </div>
      {sidebar}
      {activeModal && (
        <NameModal
          title={
            activeModal.kind === 'create-top'
              ? 'New top-level component'
              : activeModal.kind === 'create-child'
                ? `New child of "${activeModal.parent.name}"`
                : activeModal.kind === 'rename'
                  ? `Rename "${activeModal.node.name}"`
                  : `Move "${activeModal.node.name}" under…`
          }
          initial={
            'initialName' in activeModal ? activeModal.initialName : ''
          }
          onCancel={() => setActiveModal(null)}
          mode={activeModal.kind === 'move' ? 'picker' : 'text'}
          pickerOptions={
            activeModal.kind === 'move'
              ? validMoveTargets(activeModal.node)
              : undefined
          }
          onSubmit={(value, pickerId) => {
            if (activeModal.kind === 'create-top') {
              const trimmed = value.trim();
              if (!trimmed) return;
              const ins: Instruction = {
                instruction_type: 'Create',
                node_id: mintClientId('comp'),
                tier: 'comp',
                name: trimmed,
                parent_id: null,
                parent_name: null,
              };
              enqueue.mutate(ins, {
                onSuccess: () => {
                  setActiveModal(null);
                },
              });
              return;
            }
            if (activeModal.kind === 'create-child') {
              const trimmed = value.trim();
              if (!trimmed) return;
              const ins: Instruction = {
                instruction_type: 'Create',
                node_id: mintClientId('comp'),
                tier: 'comp',
                name: trimmed,
                parent_id: activeModal.parent.id,
                parent_name: activeModal.parent.name,
              };
              enqueue.mutate(ins, {
                onSuccess: () => {
                  setActiveModal(null);
                  selection.commit();
                },
              });
              return;
            }
            if (activeModal.kind === 'rename') {
              const trimmed = value.trim();
              if (!trimmed || trimmed === activeModal.node.name) {
                setActiveModal(null);
                return;
              }
              const ins: Instruction = {
                instruction_type: 'Rename',
                node_id: activeModal.node.id,
                old_name: activeModal.node.name,
                new_name: trimmed,
              };
              enqueue.mutate(ins, {
                onSuccess: () => {
                  setActiveModal(null);
                  selection.commit();
                },
              });
              return;
            }
            if (activeModal.kind === 'move') {
              const parent_id = pickerId ?? null;
              const parent_name =
                parent_id === null
                  ? null
                  : (compById.get(parent_id)?.name ?? null);
              const ins: Instruction = {
                instruction_type: 'ReassignMapping',
                node_id: activeModal.node.id,
                name: activeModal.node.name,
                new_parent_id: parent_id,
                new_parent_name: parent_name,
              };
              enqueue.mutate(ins, {
                onSuccess: () => {
                  setActiveModal(null);
                  selection.commit();
                },
              });
              return;
            }
          }}
        />
      )}
    </div>
  );
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="h-full w-full flex items-center justify-center">
      <div className="rounded border border-gray-700 bg-gray-950 p-6 text-center space-y-2 max-w-sm">
        <div className="text-sm text-gray-300">
          No components yet
        </div>
        <p className="text-xs text-gray-500">
          Sysarch seeds the tree when the project's sysarch doc is
          approved. You can also queue a top-level component
          manually below.
        </p>
        <button
          type="button"
          onClick={onCreate}
          className="rounded bg-blue-700 px-3 py-1 text-xs text-white hover:bg-blue-600"
          data-testid="decomp-empty-create"
        >
          + New top-level comp
        </button>
      </div>
    </div>
  );
}

function NameModal({
  title,
  initial,
  mode,
  pickerOptions,
  onSubmit,
  onCancel,
}: {
  title: string;
  initial: string;
  mode: 'text' | 'picker';
  pickerOptions?: Array<{ id: string | null; name: string }>;
  onSubmit: (value: string, pickerId?: string | null) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const [pickerId, setPickerId] = useState<string | null>(
    pickerOptions?.[0]?.id ?? null,
  );
  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={onCancel}
      data-testid="decomp-modal"
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded p-4 w-80 space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <h4 className="text-sm font-semibold text-gray-100">{title}</h4>
        {mode === 'text' ? (
          <input
            autoFocus
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Component name"
            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-100"
            data-testid="decomp-modal-input"
            onKeyDown={(e) => {
              if (e.key === 'Enter') onSubmit(value);
              if (e.key === 'Escape') onCancel();
            }}
          />
        ) : (
          <select
            value={pickerId ?? ''}
            onChange={(e) => setPickerId(e.target.value || null)}
            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-100"
            data-testid="decomp-modal-picker"
          >
            {(pickerOptions ?? []).map((opt) => (
              <option
                key={opt.id ?? '__top__'}
                value={opt.id ?? ''}
              >
                {opt.name}
              </option>
            ))}
          </select>
        )}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded px-3 py-1 text-xs text-gray-300 hover:bg-gray-800"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() =>
              mode === 'text' ? onSubmit(value) : onSubmit('', pickerId)
            }
            className="rounded bg-blue-700 px-3 py-1 text-xs text-white hover:bg-blue-600"
            data-testid="decomp-modal-submit"
          >
            OK
          </button>
        </div>
      </div>
    </div>
  );
}
