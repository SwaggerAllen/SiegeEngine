import { useMemo, useState } from 'react';
import type { StructureNode } from '../../api/structure';
import { mintClientId, type Instruction } from '../../api/queue';
import { useProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useEnqueueInstructionMutation } from '../../hooks/mutations/useQueueMutations';
import { describeApiError } from '../../lib/describeApiError';

interface Props {
  projectId: string;
}

/**
 * Phase 11 Structured UI #3 — decomposition editor.
 *
 * List-based MVP covering the three most-used operations:
 * ``Create`` (a new top-level or child comp), ``Rename``, and
 * ``Delete``. Promote / Demote / Merge / Split ship in follow-up
 * PRs — the instruction types already exist in the queue
 * vocabulary, so adding them later is additive.
 *
 * Renames enqueue a ``Rename`` instruction that the apply
 * handler routes through ``v2.rename_rewrite`` (see PR #6),
 * which rewrites the renamed node's content + every direct
 * consumer's content in one transaction.
 *
 * Deletes enqueue a ``Delete`` instruction. Per Phase 9 fanout
 * semantics, destructive events halt the cascade — downstream
 * nodes flip to stale but aren't regenerated automatically.
 */
export function DecompositionEditorPanel({ projectId }: Props) {
  const { data, error, isLoading } = useProjectStructure(projectId);
  const enqueue = useEnqueueInstructionMutation(projectId);
  const [newTopName, setNewTopName] = useState('');
  const [createChildFor, setCreateChildFor] = useState<string | null>(null);
  const [childName, setChildName] = useState('');

  const topLevelComps = useMemo(
    () =>
      (data?.nodes ?? [])
        .filter((n) => n.tier === 'comp' && n.parent_id === null)
        .sort((a, b) => a.display_order - b.display_order),
    [data],
  );
  const childrenByParent = useMemo(() => {
    const m = new Map<string, StructureNode[]>();
    for (const n of data?.nodes ?? []) {
      if (n.tier === 'comp' && n.parent_id) {
        const arr = m.get(n.parent_id) ?? [];
        arr.push(n);
        m.set(n.parent_id, arr);
      }
    }
    for (const arr of m.values()) arr.sort((a, b) => a.display_order - b.display_order);
    return m;
  }, [data]);

  const onCreateTopLevel = () => {
    const name = newTopName.trim();
    if (!name) return;
    const ins: Instruction = {
      instruction_type: 'Create',
      node_id: mintClientId('comp'),
      tier: 'comp',
      name,
      parent_id: null,
      parent_name: null,
    };
    enqueue.mutate(ins, { onSuccess: () => setNewTopName('') });
  };

  const onCreateChild = (parent: StructureNode) => {
    const name = childName.trim();
    if (!name) return;
    const ins: Instruction = {
      instruction_type: 'Create',
      node_id: mintClientId('comp'),
      tier: 'comp',
      name,
      parent_id: parent.id,
      parent_name: parent.name,
    };
    enqueue.mutate(ins, {
      onSuccess: () => {
        setChildName('');
        setCreateChildFor(null);
      },
    });
  };

  const onRename = (node: StructureNode) => {
    const newName = window.prompt(`Rename "${node.name}" to:`, node.name);
    if (!newName || newName.trim() === '' || newName === node.name) return;
    enqueue.mutate({
      instruction_type: 'Rename',
      node_id: node.id,
      old_name: node.name,
      new_name: newName.trim(),
    });
  };

  const onDelete = (node: StructureNode) => {
    const ok = window.confirm(
      `Queue deletion of "${node.name}"? Destructive deletes halt the downstream regen cascade — you'll need to review staleness markers after apply.`,
    );
    if (!ok) return;
    enqueue.mutate({
      instruction_type: 'Delete',
      node_id: node.id,
      name: node.name,
    });
  };

  if (isLoading) {
    return <div className="p-4 text-sm text-gray-400">Loading project structure…</div>;
  }
  if (error) {
    return (
      <div className="p-4 max-w-md">
        <h3 className="text-sm font-semibold text-red-400">Failed to load structure</h3>
        <p className="text-xs text-gray-400 mt-1">
          {describeApiError(error, 'Unknown error')}
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 max-w-3xl space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-gray-200 mb-1">Decomposition</h3>
        <p className="text-xs text-gray-400">
          Create, rename, and delete components. Every action enqueues an
          instruction — apply from the Pending Changes panel to commit.
          Renames rewrite prose in the renamed node and its direct consumers
          via <code>v2.rename_rewrite</code>. Deletes halt the fanout cascade
          so the user can review staleness markers.
        </p>
      </section>

      <section className="rounded border border-gray-700 bg-gray-950 p-3 space-y-2">
        <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide">
          Create top-level component
        </h4>
        <div className="flex items-baseline gap-2 text-sm">
          <input
            type="text"
            className="flex-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-100"
            placeholder="Component name"
            value={newTopName}
            onChange={(e) => setNewTopName(e.target.value)}
          />
          <button
            type="button"
            className="rounded bg-blue-700 px-3 py-1 text-sm text-white hover:bg-blue-600 disabled:bg-gray-700 disabled:text-gray-400"
            disabled={!newTopName.trim() || enqueue.isPending}
            onClick={onCreateTopLevel}
          >
            Queue create
          </button>
        </div>
      </section>

      <section>
        <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide mb-2">
          Components ({topLevelComps.length})
        </h4>
        {topLevelComps.length === 0 ? (
          <p className="text-sm text-gray-400">
            No top-level components yet. Sysarch approval mints them; you can
            also create new ones above.
          </p>
        ) : (
          <ul className="space-y-3 text-sm">
            {topLevelComps.map((comp) => (
              <CompRow
                key={comp.id}
                comp={comp}
                subcomps={childrenByParent.get(comp.id) ?? []}
                createChildFor={createChildFor}
                setCreateChildFor={setCreateChildFor}
                childName={childName}
                setChildName={setChildName}
                onCreateChild={onCreateChild}
                onRename={onRename}
                onDelete={onDelete}
                busy={enqueue.isPending}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function CompRow({
  comp,
  subcomps,
  createChildFor,
  setCreateChildFor,
  childName,
  setChildName,
  onCreateChild,
  onRename,
  onDelete,
  busy,
}: {
  comp: StructureNode;
  subcomps: StructureNode[];
  createChildFor: string | null;
  setCreateChildFor: (id: string | null) => void;
  childName: string;
  setChildName: (s: string) => void;
  onCreateChild: (parent: StructureNode) => void;
  onRename: (node: StructureNode) => void;
  onDelete: (node: StructureNode) => void;
  busy: boolean;
}) {
  const showChildForm = createChildFor === comp.id;
  return (
    <li className="rounded border border-gray-800 bg-gray-950 p-2">
      <div className="flex items-baseline gap-2">
        <span
          className={`shrink-0 w-3 h-3 rounded-sm ${
            comp.kind === 'presentational' ? 'bg-purple-500' : 'bg-blue-500'
          }`}
          aria-label={comp.kind}
        />
        <span className="flex-1 text-gray-100 font-medium">{comp.name}</span>
        <NodeActions
          node={comp}
          onRename={onRename}
          onDelete={onDelete}
          busy={busy}
          onAddChild={() => setCreateChildFor(showChildForm ? null : comp.id)}
        />
      </div>
      {showChildForm && (
        <div className="mt-2 ml-5 flex items-baseline gap-2 text-sm">
          <input
            type="text"
            className="flex-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-100"
            placeholder="Subcomponent name"
            value={childName}
            onChange={(e) => setChildName(e.target.value)}
          />
          <button
            type="button"
            className="rounded bg-blue-700 px-3 py-1 text-xs text-white hover:bg-blue-600 disabled:bg-gray-700"
            disabled={!childName.trim() || busy}
            onClick={() => onCreateChild(comp)}
          >
            Queue create
          </button>
          <button
            type="button"
            className="text-xs text-gray-400 hover:text-gray-200"
            onClick={() => {
              setCreateChildFor(null);
              setChildName('');
            }}
          >
            Cancel
          </button>
        </div>
      )}
      {subcomps.length > 0 && (
        <ul className="mt-2 ml-5 space-y-1">
          {subcomps.map((sub) => (
            <li key={sub.id} className="flex items-baseline gap-2 text-sm">
              <span
                className={`shrink-0 w-2 h-2 rounded-sm ${
                  sub.kind === 'presentational' ? 'bg-purple-400' : 'bg-blue-400'
                }`}
              />
              <span className="flex-1 text-gray-200">{sub.name}</span>
              <NodeActions
                node={sub}
                onRename={onRename}
                onDelete={onDelete}
                busy={busy}
              />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function NodeActions({
  node,
  onRename,
  onDelete,
  busy,
  onAddChild,
}: {
  node: StructureNode;
  onRename: (node: StructureNode) => void;
  onDelete: (node: StructureNode) => void;
  busy: boolean;
  onAddChild?: () => void;
}) {
  return (
    <div className="flex gap-2 shrink-0">
      {onAddChild && (
        <button
          type="button"
          className="text-xs text-gray-400 hover:text-gray-200 disabled:text-gray-600"
          disabled={busy}
          onClick={onAddChild}
        >
          Add child
        </button>
      )}
      <button
        type="button"
        className="text-xs text-gray-400 hover:text-gray-200 disabled:text-gray-600"
        disabled={busy}
        onClick={() => onRename(node)}
      >
        Rename
      </button>
      <button
        type="button"
        className="text-xs text-gray-400 hover:text-red-300 disabled:text-gray-600"
        disabled={busy}
        onClick={() => onDelete(node)}
      >
        Delete
      </button>
    </div>
  );
}
