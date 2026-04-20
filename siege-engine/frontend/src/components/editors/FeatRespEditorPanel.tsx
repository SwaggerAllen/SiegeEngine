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
 * Phase 11 Structured UI #1 — features → top-level responsibilities.
 *
 * Many-to-many decomposition mapping. Each feature can implicate
 * multiple responsibilities; each responsibility can be covered
 * by multiple features. Edges land in the projection as
 * ``decomposition`` edges with ``source=feat_* target=resp_*``.
 *
 * The ``reqs_*`` mint handler is the primary source of these
 * edges — this editor is for incremental corrections after
 * approval (add missing coverage, remove a false positive).
 */
export function FeatRespEditorPanel({ projectId }: Props) {
  const { data, error, isLoading } = useProjectStructure(projectId);
  const enqueue = useEnqueueInstructionMutation(projectId);
  const [sourceId, setSourceId] = useState('');
  const [targetId, setTargetId] = useState('');

  const feats = useMemo(
    () =>
      (data?.nodes ?? [])
        .filter((n) => n.tier === 'feat')
        .sort((a, b) => a.display_order - b.display_order),
    [data],
  );
  const topLevelResps = useMemo(
    () =>
      (data?.nodes ?? [])
        .filter((n) => n.tier === 'resp' && n.parent_id === null)
        .sort((a, b) => a.display_order - b.display_order),
    [data],
  );

  const nodeById = useMemo(() => {
    const m = new Map<string, StructureNode>();
    for (const n of [...feats, ...topLevelResps]) m.set(n.id, n);
    return m;
  }, [feats, topLevelResps]);

  const edges = useMemo(
    () =>
      (data?.edges ?? []).filter(
        (e) =>
          e.edge_type === 'decomposition' &&
          nodeById.get(e.source_id)?.tier === 'feat' &&
          nodeById.get(e.target_id)?.tier === 'resp',
      ),
    [data, nodeById],
  );

  const exists = (src: string, tgt: string) =>
    edges.some((e) => e.source_id === src && e.target_id === tgt);

  const disabled =
    !sourceId || !targetId || exists(sourceId, targetId) || enqueue.isPending;

  const onAdd = () => {
    const src = nodeById.get(sourceId);
    const tgt = nodeById.get(targetId);
    if (!src || !tgt) return;
    const ins: Instruction = {
      instruction_type: 'AddDecomposition',
      source_id: src.id,
      source_name: src.name,
      target_id: tgt.id,
      target_name: tgt.name,
    };
    enqueue.mutate(ins, {
      onSuccess: () => {
        setSourceId('');
        setTargetId('');
      },
    });
  };

  const onRemove = (src: string, tgt: string) => {
    const s = nodeById.get(src);
    const t = nodeById.get(tgt);
    if (!s || !t) return;
    enqueue.mutate({
      instruction_type: 'RemoveDecomposition',
      source_id: s.id,
      source_name: s.name,
      target_id: t.id,
      target_name: t.name,
    });
  };

  const onToggleDeferred = (feat: StructureNode) => {
    enqueue.mutate({
      instruction_type: 'SetFeatureDeferred',
      node_id: feat.id,
      name: feat.name,
      is_deferred: !feat.is_deferred,
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
        <h3 className="text-sm font-semibold text-gray-200 mb-1">
          Features → Responsibilities
        </h3>
        <p className="text-xs text-gray-400">
          Which features implicate which top-level responsibilities. Edits
          queue as <code>AddDecomposition</code> /{' '}
          <code>RemoveDecomposition</code> instructions. Sysarch's
          downstream regens read this graph via the many-to-many walk;
          changes mark affected components stale after apply.
        </p>
      </section>

      <section>
        <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide mb-2">
          Feature deferral
        </h4>
        <p className="text-xs text-gray-400 mb-2">
          Deferred features stay visible here and in the DAG, but reqs and
          sysarch regens skip them. Use this for capabilities you're
          designing toward but don't want the current pipeline to commit
          structure for.
        </p>
        <ul className="space-y-1 text-sm">
          {feats.map((f) => (
            <li key={f.id} className="flex items-baseline gap-2">
              <span
                className={`flex-1 truncate ${
                  f.is_deferred ? 'text-gray-500 italic' : 'text-gray-200'
                }`}
              >
                {f.name}
                {f.is_deferred ? ' (deferred)' : ''}
              </span>
              <button
                type="button"
                className="shrink-0 text-xs text-gray-400 hover:text-gray-200 disabled:text-gray-600"
                disabled={enqueue.isPending}
                onClick={() => onToggleDeferred(f)}
              >
                {f.is_deferred ? 'Queue un-defer' : 'Queue defer'}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded border border-gray-700 bg-gray-950 p-3 space-y-2">
        <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide">
          Add coverage
        </h4>
        <div className="flex flex-wrap items-baseline gap-2 text-sm">
          <label className="flex items-baseline gap-1">
            <span className="text-gray-400">Feature</span>
            <select
              className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-100"
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
            >
              <option value="">— select feature —</option>
              {feats.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </label>
          <span className="text-gray-500">implicates</span>
          <label className="flex items-baseline gap-1">
            <span className="text-gray-400">Responsibility</span>
            <select
              className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-100"
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
            >
              <option value="">— select responsibility —</option>
              {topLevelResps.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="rounded bg-blue-700 px-3 py-1 text-sm text-white hover:bg-blue-600 disabled:bg-gray-700 disabled:text-gray-400"
            disabled={disabled}
            onClick={onAdd}
          >
            {enqueue.isPending ? 'Queuing…' : 'Queue add'}
          </button>
        </div>
        {sourceId && targetId && exists(sourceId, targetId) && (
          <p className="text-xs text-gray-400">This coverage edge already exists.</p>
        )}
      </section>

      <section>
        <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide mb-2">
          Coverage ({edges.length})
        </h4>
        {edges.length === 0 ? (
          <p className="text-sm text-gray-400">
            No feat→resp coverage edges yet. Reqs mint seeds them at approval
            time.
          </p>
        ) : (
          <ul className="space-y-1 text-sm">
            {edges.map((e) => {
              const src = nodeById.get(e.source_id);
              const tgt = nodeById.get(e.target_id);
              const label =
                src && tgt
                  ? `${src.name} → ${tgt.name}`
                  : `${e.source_id} → ${e.target_id}`;
              return (
                <li key={e.id} className="flex items-baseline gap-2">
                  <span className="flex-1 truncate text-gray-200">{label}</span>
                  <button
                    type="button"
                    className="shrink-0 text-xs text-gray-400 hover:text-red-300 disabled:text-gray-600"
                    disabled={enqueue.isPending}
                    onClick={() => onRemove(e.source_id, e.target_id)}
                  >
                    Queue remove
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
