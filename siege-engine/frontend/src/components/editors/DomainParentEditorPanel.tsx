import { useMemo, useState } from 'react';
import type { Instruction } from '../../api/queue';
import { useProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useEnqueueInstructionMutation } from '../../hooks/mutations/useQueueMutations';
import { describeApiError } from '../../lib/describeApiError';

interface Props {
  projectId: string;
}

/**
 * Phase 11 Structured UI #6 — domain-parent editor.
 *
 * Domain-parent edges mark a presentational component as a primary
 * view into a domain component. Direction is presentational →
 * domain, many-to-many (one presentational can map to multiple
 * domain parents). Not a dependency edge; the regen-context path
 * for presentational comparch walks these edges via
 * ``all_domain_parents_have_populated_fanin`` (Phase 7.5) to block
 * until the domain fan-ins exist.
 *
 * Cycle detection is **not** run on domain-parent edges —
 * presentational comps are strictly layered after domain comps,
 * so by construction these can't close a cycle with dep edges.
 */
export function DomainParentEditorPanel({ projectId }: Props) {
  const { data, error, isLoading } = useProjectStructure(projectId);
  const enqueue = useEnqueueInstructionMutation(projectId);
  const [sourceId, setSourceId] = useState('');
  const [targetId, setTargetId] = useState('');

  const allComps = useMemo(
    () =>
      (data?.nodes ?? [])
        .filter((n) => n.tier === 'comp')
        .sort((a, b) => a.name.localeCompare(b.name)),
    [data],
  );
  const presentationalComps = useMemo(
    () => allComps.filter((c) => c.kind === 'presentational'),
    [allComps],
  );
  const domainComps = useMemo(
    () => allComps.filter((c) => c.kind === 'domain'),
    [allComps],
  );

  const compById = useMemo(() => {
    const m = new Map<string, (typeof allComps)[number]>();
    for (const c of allComps) m.set(c.id, c);
    return m;
  }, [allComps]);

  const edges = useMemo(
    () => (data?.edges ?? []).filter((e) => e.edge_type === 'domain_parent'),
    [data],
  );

  const alreadyExists = (src: string, tgt: string) =>
    edges.some((e) => e.source_id === src && e.target_id === tgt);

  const disabled =
    !sourceId ||
    !targetId ||
    alreadyExists(sourceId, targetId) ||
    enqueue.isPending;

  const onAdd = () => {
    const src = compById.get(sourceId);
    const tgt = compById.get(targetId);
    if (!src || !tgt) return;
    const ins: Instruction = {
      instruction_type: 'AddDomainParent',
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
    const s = compById.get(src);
    const t = compById.get(tgt);
    if (!s || !t) return;
    enqueue.mutate({
      instruction_type: 'RemoveDomainParent',
      source_id: s.id,
      source_name: s.name,
      target_id: t.id,
      target_name: t.name,
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
        <h3 className="text-sm font-semibold text-gray-200 mb-1">Domain parents</h3>
        <p className="text-xs text-gray-400">
          Mark a presentational component as a primary view into a domain
          component. The presentational comparch sees the domain's fan-in
          synthesis as context; adding a domain parent here gates the
          presentational's comparch on the domain's first-pass completion.
        </p>
      </section>

      <section className="rounded border border-gray-700 bg-gray-950 p-3 space-y-2">
        <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide">
          Add domain parent
        </h4>
        <div className="flex flex-wrap items-baseline gap-2 text-sm">
          <label className="flex items-baseline gap-1">
            <span className="text-gray-400">Presentational</span>
            <select
              className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-100"
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
            >
              <option value="">— select presentational —</option>
              {presentationalComps.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <span className="text-gray-500">presents</span>
          <label className="flex items-baseline gap-1">
            <span className="text-gray-400">Domain</span>
            <select
              className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-100"
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
            >
              <option value="">— select domain —</option>
              {domainComps.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
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
        {sourceId && targetId && alreadyExists(sourceId, targetId) && (
          <p className="text-xs text-gray-400">This domain-parent edge already exists.</p>
        )}
        {presentationalComps.length === 0 && (
          <p className="text-xs text-amber-300">
            No presentational components exist yet. Sysarch needs to approve at
            least one presentational comp before this editor is meaningful.
          </p>
        )}
      </section>

      <section>
        <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide mb-2">
          Existing domain parents ({edges.length})
        </h4>
        {edges.length === 0 ? (
          <p className="text-sm text-gray-400">No domain-parent edges yet.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {edges.map((e) => {
              const src = compById.get(e.source_id);
              const tgt = compById.get(e.target_id);
              const label =
                src && tgt
                  ? `${src.name} presents ${tgt.name}`
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
