import { useMemo } from 'react';
import type { StructureNode } from '../../api/structure';
import type { Instruction } from '../../api/queue';
import { useProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useEnqueueInstructionMutation } from '../../hooks/mutations/useQueueMutations';
import { describeApiError } from '../../lib/describeApiError';

interface Props {
  projectId: string;
}

/**
 * Phase 11 Structured UI #2 — top-level responsibilities → components.
 *
 * Each top-level ``resp_*`` is assigned to exactly one domain
 * component via a ``decomposition`` edge (resp → comp). The sysarch
 * mint handler seeds these edges; this editor lets the user adjust
 * individual assignments post-approval.
 *
 * Changing a resp's assigned comp enqueues two instructions in
 * order: ``RemoveDecomposition`` on the current edge (if any),
 * then ``AddDecomposition`` on the new one. The apply handler
 * drains them sequentially.
 */
export function RespCompEditorPanel({ projectId }: Props) {
  const { data, error, isLoading } = useProjectStructure(projectId);
  const enqueue = useEnqueueInstructionMutation(projectId);

  const topLevelResps = useMemo(
    () =>
      (data?.nodes ?? [])
        .filter((n) => n.tier === 'resp' && n.parent_id === null)
        .sort((a, b) => a.display_order - b.display_order),
    [data],
  );
  const topLevelComps = useMemo(
    () =>
      (data?.nodes ?? [])
        .filter(
          (n) => n.tier === 'comp' && n.parent_id === null && n.kind === 'domain',
        )
        .sort((a, b) => a.display_order - b.display_order),
    [data],
  );

  const nodeById = useMemo(() => {
    const m = new Map<string, StructureNode>();
    for (const n of data?.nodes ?? []) m.set(n.id, n);
    return m;
  }, [data]);

  // For each top-level resp, find its current (single) assigned
  // domain comp via the decomposition edge (resp → comp).
  const assignmentByResp = useMemo(() => {
    const m = new Map<string, { compId: string; edgeId: string }>();
    for (const e of data?.edges ?? []) {
      if (e.edge_type !== 'decomposition') continue;
      const src = nodeById.get(e.source_id);
      const tgt = nodeById.get(e.target_id);
      if (!src || !tgt) continue;
      if (src.tier !== 'resp' || src.parent_id !== null) continue;
      if (tgt.tier !== 'comp' || tgt.parent_id !== null) continue;
      if (tgt.kind !== 'domain') continue;
      m.set(e.source_id, { compId: e.target_id, edgeId: e.id });
    }
    return m;
  }, [data, nodeById]);

  const onReassign = (resp: StructureNode, newCompId: string) => {
    const current = assignmentByResp.get(resp.id);
    if (current?.compId === newCompId) return;
    const newComp = topLevelComps.find((c) => c.id === newCompId);
    if (!newComp) return;

    // Remove the existing edge (if any), then add the new one.
    // Two separate instructions; apply handler drains them in
    // sequence order.
    if (current) {
      const currentComp = nodeById.get(current.compId);
      if (currentComp) {
        const removeIns: Instruction = {
          instruction_type: 'RemoveDecomposition',
          source_id: resp.id,
          source_name: resp.name,
          target_id: current.compId,
          target_name: currentComp.name,
        };
        enqueue.mutate(removeIns);
      }
    }
    const addIns: Instruction = {
      instruction_type: 'AddDecomposition',
      source_id: resp.id,
      source_name: resp.name,
      target_id: newComp.id,
      target_name: newComp.name,
    };
    enqueue.mutate(addIns);
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
          Responsibilities → Components
        </h3>
        <p className="text-xs text-gray-400">
          Each top-level responsibility is assigned to exactly one domain
          component. Changing the dropdown queues a{' '}
          <code>RemoveDecomposition</code> (current edge) + an{' '}
          <code>AddDecomposition</code> (new edge) in that order. The assign
          semantics are 1:1 — if a resp should span multiple comps, split
          it into two resps via the decomposition editor first.
        </p>
      </section>

      {topLevelResps.length === 0 ? (
        <p className="text-sm text-gray-400">
          No top-level responsibilities yet. Reqs mint seeds them.
        </p>
      ) : (
        <section>
          <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide mb-2">
            Assignments ({topLevelResps.length})
          </h4>
          <ul className="space-y-1 text-sm">
            {topLevelResps.map((resp) => {
              const current = assignmentByResp.get(resp.id);
              return (
                <li key={resp.id} className="flex items-baseline gap-2">
                  <span className="flex-1 truncate text-gray-200">{resp.name}</span>
                  <label className="text-xs text-gray-400">
                    Assigned to
                    <select
                      className="ml-1 bg-gray-900 border border-gray-700 rounded px-1 text-gray-100"
                      value={current?.compId ?? ''}
                      onChange={(e) => onReassign(resp, e.target.value)}
                      disabled={enqueue.isPending || topLevelComps.length === 0}
                    >
                      <option value="">— unassigned —</option>
                      {topLevelComps.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </li>
              );
            })}
          </ul>
          {topLevelComps.length === 0 && (
            <p className="mt-2 text-xs text-amber-300">
              No top-level domain components yet. Run sysarch to mint them.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
