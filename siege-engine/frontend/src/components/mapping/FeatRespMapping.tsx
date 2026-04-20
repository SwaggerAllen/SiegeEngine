import { useMemo } from 'react';
import { useProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useEnqueueInstruction } from '../../hooks/queries/useProjectQueue';
import { MappingItem, TwoColumnMapping } from './TwoColumnMapping';

interface Props {
  projectId: string;
}

/**
 * Structured UI #1 — feature → responsibility mapping.
 *
 * Drag a `feat_*` card onto a top-level `resp_*` card to enqueue
 * `AddDecomposition(feat → resp)`. Click a chip's detach button
 * to enqueue `RemoveDecomposition`. Nothing applies until the user
 * opens the Pending Changes panel and hits Apply.
 */
export function FeatRespMapping({ projectId }: Props) {
  const { data, isLoading, error } = useProjectStructure(projectId);
  const enqueue = useEnqueueInstruction(projectId);

  const { features, topResps, attachmentsByResp, byId } = useMemo(() => {
    const feats: MappingItem[] = [];
    const resps: MappingItem[] = [];
    const attach: Record<string, MappingItem[]> = {};
    const index = new Map<string, MappingItem>();
    if (!data) {
      return {
        features: feats,
        topResps: resps,
        attachmentsByResp: attach,
        byId: index,
      };
    }
    for (const n of data.nodes) {
      if (n.tier === 'feat') {
        const item = { id: n.id, name: n.name };
        feats.push(item);
        index.set(n.id, item);
      } else if (n.tier === 'resp' && n.parent_id === null) {
        const item = { id: n.id, name: n.name };
        resps.push(item);
        index.set(n.id, item);
        attach[n.id] = [];
      }
    }
    for (const e of data.edges) {
      if (e.edge_type !== 'decomposition') continue;
      const src = index.get(e.source_id);
      const dst = attach[e.target_id];
      if (src && dst) dst.push(src);
    }
    return {
      features: feats,
      topResps: resps,
      attachmentsByResp: attach,
      byId: index,
    };
  }, [data]);

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

  const onAttach = (sourceId: string, targetId: string) => {
    const src = byId.get(sourceId);
    const dst = byId.get(targetId);
    if (!src || !dst) return;
    const alreadyAttached = (attachmentsByResp[targetId] ?? []).some(
      (c) => c.id === sourceId,
    );
    if (alreadyAttached) return;
    enqueue.mutate({
      instruction_type: 'AddDecomposition',
      source_id: src.id,
      source_name: src.name,
      target_id: dst.id,
      target_name: dst.name,
    });
  };

  const onDetach = (sourceId: string, targetId: string) => {
    const src = byId.get(sourceId);
    const dst = byId.get(targetId);
    if (!src || !dst) return;
    enqueue.mutate({
      instruction_type: 'RemoveDecomposition',
      source_id: src.id,
      source_name: src.name,
      target_id: dst.id,
      target_name: dst.name,
    });
  };

  return (
    <div className="h-full w-full flex flex-col">
      <div className="border-b border-gray-800 px-4 py-2 text-xs text-gray-400">
        Drag a feature onto a responsibility to queue an attachment.
        Changes land in the Pending Changes queue.
      </div>
      <div className="flex-1 min-h-0">
        <TwoColumnMapping
          sourceLabel="Features"
          sourceItems={features}
          targetLabel="Top-level responsibilities"
          targetItems={topResps}
          attachmentsByTarget={attachmentsByResp}
          onAttach={onAttach}
          onDetach={onDetach}
        />
      </div>
    </div>
  );
}
