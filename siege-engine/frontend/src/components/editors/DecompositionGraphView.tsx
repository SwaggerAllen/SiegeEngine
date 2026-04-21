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
 * Rename, Delete, Move under…, Split into….
 *
 * **Multi-select** (PR-11b). A "Select multiple" toolbar toggle
 * flips the graph into multi-select mode. Taps add/remove nodes
 * from the selection set; when 2+ same-parent same-tier comps
 * are selected, a "Merge selected…" action appears in the
 * sidebar and opens a Merge modal.
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
    | { kind: 'merge'; nodes: StructureNode[] }
    | { kind: 'split'; node: StructureNode }
  >(null);
  const [multiSelect, setMultiSelect] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

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
  const singleSelection = useEditableGraphSelection({ canConnect: () => false });

  // When multiSelect is active, we hijack tap routing so taps
  // toggle ids in `selectedIds` instead of going to the
  // single-select state machine. The selection object exposed to
  // EditableGraph is still the single-select one (for its class
  // application behavior around selected-source), but the tap
  // handlers it sees are replaced.
  const selection = useMemo(() => {
    if (!multiSelect) return singleSelection;
    return {
      ...singleSelection,
      onNodeTap: (id: string) => {
        setSelectedIds((prev) => {
          const next = new Set(prev);
          if (next.has(id)) next.delete(id);
          else next.add(id);
          return next;
        });
      },
      onEdgeTap: () => {},
      onBackgroundTap: () => {},
      state: { kind: 'idle' as const },
    };
  }, [multiSelect, singleSelection]);

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

  // Multi-select sidebar — appears whenever multiSelect mode is
  // active. Shows the current count and, when ≥ 2 same-parent
  // same-tier comps are selected, a Merge action.
  const mergeCandidates = useMemo(() => {
    const picked = Array.from(selectedIds)
      .map((id) => compById.get(id))
      .filter((n): n is StructureNode => !!n);
    if (picked.length < 2) return null;
    const firstParent = picked[0].parent_id;
    const firstTier = picked[0].tier;
    const allMatch = picked.every(
      (n) => n.parent_id === firstParent && n.tier === firstTier,
    );
    return allMatch ? picked : null;
  }, [selectedIds, compById]);

  const multiSelectSidebar =
    multiSelect ? (
      <NodeActionSidebar
        title={`${selectedIds.size} selected`}
        subtitle="Multi-select mode"
        onCancel={() => {
          setSelectedIds(new Set());
        }}
        actions={
          <div className="space-y-1.5">
            {mergeCandidates ? (
              <SidebarActionButton
                label="Merge selected…"
                variant="primary"
                testId="decomp-action-merge"
                onClick={() =>
                  setActiveModal({ kind: 'merge', nodes: mergeCandidates })
                }
              />
            ) : (
              <p className="text-xs text-gray-400">
                Select 2+ sibling comps of the same tier to enable Merge.
              </p>
            )}
            <SidebarActionButton
              label="Exit multi-select"
              testId="decomp-action-exit-multi"
              onClick={() => {
                setMultiSelect(false);
                setSelectedIds(new Set());
              }}
            />
          </div>
        }
      />
    ) : null;

  const sidebar = (() => {
    if (multiSelect) return multiSelectSidebar;
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
              label="Split into…"
              testId="decomp-action-split"
              onClick={() => setActiveModal({ kind: 'split', node })}
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
          <button
            type="button"
            onClick={() => {
              setMultiSelect((v) => !v);
              setSelectedIds(new Set());
            }}
            className={`rounded px-2 py-0.5 ${
              multiSelect
                ? 'bg-amber-600 text-white hover:bg-amber-500'
                : 'bg-gray-800 text-gray-200 hover:bg-gray-700'
            }`}
            data-testid="decomp-toggle-multi"
            aria-pressed={multiSelect}
          >
            {multiSelect ? 'Exit multi-select' : 'Select multiple'}
          </button>
          <span className="text-gray-500">
            {multiSelect
              ? `Tap comps to build a merge set. ${selectedIds.size} selected.`
              : 'Tap a comp to open actions.'}
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
              multiSelectIds={multiSelect ? selectedIds : undefined}
            />
          )}
        </div>
      </div>
      {sidebar}
      {activeModal?.kind === 'merge' && (
        <MergeModal
          nodes={activeModal.nodes}
          onCancel={() => setActiveModal(null)}
          onSubmit={({ destId, destName }) => {
            const ins: Instruction = {
              instruction_type: 'Merge',
              source_ids: activeModal.nodes.map((n) => n.id),
              source_names: activeModal.nodes.map((n) => n.name),
              dest_id: destId,
              dest_name: destName,
            };
            enqueue.mutate(ins, {
              onSuccess: () => {
                setActiveModal(null);
                setSelectedIds(new Set());
                setMultiSelect(false);
              },
            });
          }}
        />
      )}
      {activeModal?.kind === 'split' && (
        <SplitModal
          node={activeModal.node}
          onCancel={() => setActiveModal(null)}
          onSubmit={(destNames) => {
            const destIds = destNames.map(() => mintClientId('comp'));
            const ins: Instruction = {
              instruction_type: 'Split',
              source_id: activeModal.node.id,
              source_name: activeModal.node.name,
              dest_ids: destIds,
              dest_names: destNames,
            };
            enqueue.mutate(ins, {
              onSuccess: () => {
                setActiveModal(null);
                selection.commit();
              },
            });
          }}
        />
      )}
      {activeModal &&
        activeModal.kind !== 'merge' &&
        activeModal.kind !== 'split' && (
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

/**
 * Merge modal — pick destination identity (reuse one of the
 * selected sources' IDs, or mint a brand new one) and a name.
 * The backend ``Merge`` handler rewrites children / edges from
 * the discarded sources to the dest. Downstream cascade halts
 * per Phase 9.
 */
function MergeModal({
  nodes,
  onCancel,
  onSubmit,
}: {
  nodes: StructureNode[];
  onCancel: () => void;
  onSubmit: (args: { destId: string; destName: string }) => void;
}) {
  const [destChoice, setDestChoice] = useState<string>(nodes[0].id);
  const [name, setName] = useState<string>(nodes[0].name);
  const destId = destChoice === '__new__' ? mintClientId('comp') : destChoice;
  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={onCancel}
      data-testid="decomp-merge-modal"
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded p-4 w-96 space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <h4 className="text-sm font-semibold text-gray-100">
          Merge {nodes.length} components
        </h4>
        <p className="text-xs text-gray-400">
          Sources: {nodes.map((n) => `"${n.name}"`).join(', ')}.
        </p>
        <label className="block text-xs text-gray-300">
          Destination identity
          <select
            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-100 mt-1"
            value={destChoice}
            onChange={(e) => {
              const v = e.target.value;
              setDestChoice(v);
              if (v !== '__new__') {
                const keep = nodes.find((n) => n.id === v);
                if (keep) setName(keep.name);
              }
            }}
            data-testid="decomp-merge-dest-choice"
          >
            {nodes.map((n) => (
              <option key={n.id} value={n.id}>
                Keep "{n.name}" ({n.id})
              </option>
            ))}
            <option value="__new__">New node (mint fresh id)</option>
          </select>
        </label>
        <label className="block text-xs text-gray-300">
          Destination name
          <input
            type="text"
            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-100 mt-1"
            value={name}
            onChange={(e) => setName(e.target.value)}
            data-testid="decomp-merge-dest-name"
          />
        </label>
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
            disabled={!name.trim()}
            onClick={() => onSubmit({ destId, destName: name.trim() })}
            className="rounded bg-amber-600 px-3 py-1 text-xs text-white hover:bg-amber-500 disabled:opacity-40"
            data-testid="decomp-merge-submit"
          >
            Queue merge
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Split modal — one source comp splits into N new comps.
 * Backend halts the downstream cascade; user resolves mapping
 * by regenerating child tiers after approval.
 */
function SplitModal({
  node,
  onCancel,
  onSubmit,
}: {
  node: StructureNode;
  onCancel: () => void;
  onSubmit: (destNames: string[]) => void;
}) {
  const [names, setNames] = useState<string[]>([`${node.name} A`, `${node.name} B`]);
  const addRow = () => setNames((prev) => [...prev, '']);
  const setRow = (i: number, v: string) =>
    setNames((prev) => prev.map((n, idx) => (idx === i ? v : n)));
  const removeRow = (i: number) =>
    setNames((prev) => prev.filter((_, idx) => idx !== i));
  const cleaned = names.map((n) => n.trim()).filter((n) => n.length > 0);
  const disabled = cleaned.length < 2;
  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={onCancel}
      data-testid="decomp-split-modal"
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded p-4 w-96 space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <h4 className="text-sm font-semibold text-gray-100">
          Split "{node.name}" into…
        </h4>
        <p className="text-xs text-gray-400">
          Mints {cleaned.length || '?'} new components. The downstream
          cascade halts so you can resolve which child / covered
          features map to which split target by regenerating child
          tiers after the queue applies.
        </p>
        <div className="space-y-1.5">
          {names.map((n, i) => (
            <div key={i} className="flex gap-2">
              <input
                type="text"
                value={n}
                onChange={(e) => setRow(i, e.target.value)}
                className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-100"
                placeholder={`Split target ${i + 1} name`}
                data-testid={`decomp-split-name-${i}`}
              />
              {names.length > 2 && (
                <button
                  type="button"
                  onClick={() => removeRow(i)}
                  className="text-xs text-gray-500 hover:text-red-300"
                  aria-label={`Remove split target ${i + 1}`}
                >
                  ✕
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            onClick={addRow}
            className="text-xs text-gray-400 hover:text-gray-200"
            data-testid="decomp-split-add-row"
          >
            + Add another
          </button>
        </div>
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
            disabled={disabled}
            onClick={() => onSubmit(cleaned)}
            className="rounded bg-amber-600 px-3 py-1 text-xs text-white hover:bg-amber-500 disabled:opacity-40"
            data-testid="decomp-split-submit"
          >
            Queue split
          </button>
        </div>
      </div>
    </div>
  );
}
