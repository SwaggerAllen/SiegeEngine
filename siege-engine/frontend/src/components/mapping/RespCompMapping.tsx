import { useMemo } from 'react';
import { useProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useEnqueueInstruction } from '../../hooks/queries/useProjectQueue';
import { MappingItem, TwoColumnMapping } from './TwoColumnMapping';

interface Props {
  projectId: string;
}

/**
 * Structured UI #2 — responsibility → component mapping.
 *
 * Top-level resps map 1:1 to top-level comps via decomposition
 * edges. Drag a resp onto a comp to enqueue
 * `ReassignMapping(resp, new_parent=comp)`. Chip-detach enqueues
 * `ReassignMapping` with `new_parent=null` — useful for clearing
 * an assignment before re-attaching elsewhere.
 */
export function RespCompMapping({ projectId }: Props) {
  const { data, isLoading, error } = useProjectStructure(projectId);
  const enqueue = useEnqueueInstruction(projectId);

  const { topResps, topComps, attachmentsByComp, byId, compIndex } = useMemo(
    () => {
      const resps: MappingItem[] = [];
      const comps: MappingItem[] = [];
      const attach: Record<string, MappingItem[]> = {};
      const index = new Map<string, MappingItem>();
      const compMap = new Map<string, string>(); // resp_id → comp_id
      if (!data) {
        return {
          topResps: resps,
          topComps: comps,
          attachmentsByComp: attach,
          byId: index,
          compIndex: compMap,
        };
      }
      for (const n of data.nodes) {
        if (n.tier === 'resp' && n.parent_id === null) {
          const item = { id: n.id, name: n.name };
          resps.push(item);
          index.set(n.id, item);
        } else if (n.tier === 'comp' && n.parent_id === null) {
          const item = { id: n.id, name: n.name };
          comps.push(item);
          index.set(n.id, item);
          attach[n.id] = [];
        }
      }
      // Resp→comp assignment lives in decomposition edges from
      // top-level resps into top-level comps.
      for (const e of data.edges) {
        if (e.edge_type !== 'decomposition') continue;
        const src = index.get(e.source_id);
        const dstBucket = attach[e.target_id];
        const dstNode = data.nodes.find((n) => n.id === e.target_id);
        if (!src || !dstBucket || dstNode?.tier !== 'comp') continue;
        dstBucket.push(src);
        compMap.set(src.id, e.target_id);
      }
      return {
        topResps: resps,
        topComps: comps,
        attachmentsByComp: attach,
        byId: index,
        compIndex: compMap,
      };
    },
    [data],
  );

  if (isLoading) {
    return <div className="p-6 text-sm text-gray-400">Loading mapping…</div>;
  }
  if (error || !data) {
    return (
      <div className="p-6 text-sm text-red-400">
        Failed to load the structure.
      </div>
    );
  }

  const onAttach = (respId: string, compId: string) => {
    const resp = byId.get(respId);
    const comp = byId.get(compId);
    if (!resp || !comp) return;
    if (compIndex.get(respId) === compId) return; // already attached
    enqueue.mutate({
      instruction_type: 'ReassignMapping',
      node_id: resp.id,
      name: resp.name,
      new_parent_id: comp.id,
      new_parent_name: comp.name,
    });
  };

  const onDetach = (respId: string) => {
    const resp = byId.get(respId);
    if (!resp) return;
    enqueue.mutate({
      instruction_type: 'ReassignMapping',
      node_id: resp.id,
      name: resp.name,
      new_parent_id: null,
      new_parent_name: null,
    });
  };

  return (
    <div className="h-full w-full flex flex-col">
      <div className="border-b border-gray-800 px-4 py-2 text-xs text-gray-400">
        Drag a responsibility onto a component to queue a re-assignment.
        Each resp belongs to exactly one comp.
      </div>
      <div className="flex-1 min-h-0">
        <TwoColumnMapping
          sourceLabel="Top-level responsibilities"
          sourceItems={topResps}
          targetLabel="Top-level components"
          targetItems={topComps}
          attachmentsByTarget={attachmentsByComp}
          onAttach={onAttach}
          onDetach={(sid) => onDetach(sid)}
        />
      </div>
    </div>
  );
}
