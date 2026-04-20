import { useMemo, useState } from 'react';
import type { StructureNode } from '../../api/structure';
import type { Instruction } from '../../api/queue';
import { useProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useEnqueueInstructionMutation } from '../../hooks/mutations/useQueueMutations';
import { describeApiError } from '../../lib/describeApiError';

interface Props {
  projectId: string;
}

/**
 * Phase 11 Structured UI #4 — subresponsibility → subcomponent
 * mapping editor.
 *
 * Subresps are ``resp_*`` nodes whose ``parent_id`` points at a
 * subcomponent (``comp_*`` with its own parent). Reassigning a
 * subresp to a different subcomponent within the same top-level
 * component is a ``ReassignMapping`` instruction that flips
 * ``parent_id`` — the rest of the model (decomposition edges
 * pointing at the subresp from top-level resps, any fragments
 * owned by the subresp) stays intact.
 *
 * Scope: within one top-level component's subtree. Cross-parent
 * moves (subresp A under comp_X → comp_Y) are rejected by
 * architectural invariant — the subreqs bootstrap scopes each
 * subresp to its owning comp.
 */
export function SubrespSubcompEditorPanel({ projectId }: Props) {
  const { data, error, isLoading } = useProjectStructure(projectId);
  const enqueue = useEnqueueInstructionMutation(projectId);
  const [selectedTopId, setSelectedTopId] = useState('');

  const topLevelComps = useMemo(
    () =>
      (data?.nodes ?? [])
        .filter((n) => n.tier === 'comp' && n.parent_id === null)
        .sort((a, b) => a.display_order - b.display_order),
    [data],
  );

  const subcompsOfTop = useMemo(() => {
    if (!selectedTopId || !data) return [] as StructureNode[];
    return data.nodes
      .filter((n) => n.tier === 'comp' && n.parent_id === selectedTopId)
      .sort((a, b) => a.display_order - b.display_order);
  }, [data, selectedTopId]);

  const subcompIds = useMemo(
    () => new Set(subcompsOfTop.map((s) => s.id)),
    [subcompsOfTop],
  );

  // Subresps of the selected top: resp nodes whose parent_id is
  // the top-level comp (pre-comparch-mint state) OR one of its
  // subcomps (post-mint state).
  const subrespsOfTop = useMemo(() => {
    if (!selectedTopId || !data) return [] as StructureNode[];
    return data.nodes
      .filter(
        (n) =>
          n.tier === 'resp' &&
          n.parent_id !== null &&
          (n.parent_id === selectedTopId || subcompIds.has(n.parent_id)),
      )
      .sort((a, b) => a.display_order - b.display_order);
  }, [data, selectedTopId, subcompIds]);

  const onReassign = (sub: StructureNode, newParentId: string) => {
    if (sub.parent_id === newParentId) return;
    const newParent =
      subcompsOfTop.find((s) => s.id === newParentId) ??
      topLevelComps.find((c) => c.id === newParentId);
    if (!newParent) return;
    const ins: Instruction = {
      instruction_type: 'ReassignMapping',
      node_id: sub.id,
      name: sub.name,
      new_parent_id: newParentId,
      new_parent_name: newParent.name,
    };
    enqueue.mutate(ins);
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
        <h3 className="text-sm font-semibold text-gray-200 mb-1">
          Subresponsibilities → Subcomponents
        </h3>
        <p className="text-xs text-gray-400">
          Reassign a subresponsibility to a different subcomponent within the
          same top-level component. Each move queues a{' '}
          <code>ReassignMapping</code> instruction that flips the subresp's
          parent when applied.
        </p>
      </section>

      <section className="rounded border border-gray-700 bg-gray-950 p-3 space-y-2">
        <label className="text-xs text-gray-300">
          Top-level component
          <select
            className="ml-2 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-100"
            value={selectedTopId}
            onChange={(e) => setSelectedTopId(e.target.value)}
          >
            <option value="">— select —</option>
            {topLevelComps.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        {selectedTopId && subcompsOfTop.length === 0 && (
          <p className="text-xs text-amber-300">
            This component has no subcomponents yet. Run comparch to mint them
            before subresps can be reassigned.
          </p>
        )}
      </section>

      {selectedTopId && subrespsOfTop.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide mb-2">
            Subresponsibilities ({subrespsOfTop.length})
          </h4>
          <ul className="space-y-1 text-sm">
            {subrespsOfTop.map((sub) => (
              <li key={sub.id} className="flex items-baseline gap-2">
                <span className="flex-1 truncate text-gray-200">{sub.name}</span>
                <label className="text-xs text-gray-400">
                  Parent
                  <select
                    className="ml-1 bg-gray-900 border border-gray-700 rounded px-1 text-gray-100"
                    value={sub.parent_id ?? ''}
                    onChange={(e) => onReassign(sub, e.target.value)}
                    disabled={enqueue.isPending}
                  >
                    <option value={selectedTopId}>
                      (top-level: {topLevelComps.find((c) => c.id === selectedTopId)?.name})
                    </option>
                    {subcompsOfTop.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </label>
              </li>
            ))}
          </ul>
        </section>
      )}

      {selectedTopId && subrespsOfTop.length === 0 && (
        <p className="text-sm text-gray-400">
          No subresponsibilities exist under this top-level component yet.
        </p>
      )}
    </div>
  );
}
