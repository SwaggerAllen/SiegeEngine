import { useMemo, useState } from 'react';
import type { Instruction } from '../../api/queue';
import { useProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useEnqueueInstructionMutation } from '../../hooks/mutations/useQueueMutations';
import { describeApiError } from '../../lib/describeApiError';

interface Props {
  projectId: string;
}

/**
 * Phase 11 Structured UI #5 — dependency editor.
 *
 * List-based MVP (Cytoscape drag-to-connect is a post-MVP polish).
 * Shows every ``dependency`` edge in the project plus an "add"
 * form at the top. Edits don't mutate the model directly — they
 * enqueue ``AddDependency`` / ``RemoveDependency`` instructions
 * that the user applies via the Pending Changes panel.
 *
 * Scope: operates on top-level ``comp_*`` nodes and subcomponents.
 * The scope of "which comp can depend on which" is enforced
 * server-side (see sysarch parser cycle detection + the Phase 11
 * ``would_create_cycle`` helper).
 */
export function DependencyEditorPanel({ projectId }: Props) {
  const { data, error, isLoading } = useProjectStructure(projectId);
  const enqueue = useEnqueueInstructionMutation(projectId);
  const [sourceId, setSourceId] = useState('');
  const [targetId, setTargetId] = useState('');

  const comps = useMemo(
    () =>
      (data?.nodes ?? [])
        .filter((n) => n.tier === 'comp')
        .sort((a, b) => a.name.localeCompare(b.name)),
    [data],
  );

  const compById = useMemo(() => {
    const m = new Map<string, (typeof comps)[number]>();
    for (const c of comps) m.set(c.id, c);
    return m;
  }, [comps]);

  const deps = useMemo(
    () => (data?.edges ?? []).filter((e) => e.edge_type === 'dependency'),
    [data],
  );

  const alreadyExists = (src: string, tgt: string) =>
    deps.some((e) => e.source_id === src && e.target_id === tgt);

  const disabled =
    !sourceId ||
    !targetId ||
    sourceId === targetId ||
    alreadyExists(sourceId, targetId) ||
    enqueue.isPending;

  const onAdd = () => {
    const src = compById.get(sourceId);
    const tgt = compById.get(targetId);
    if (!src || !tgt) return;
    const ins: Instruction = {
      instruction_type: 'AddDependency',
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
      instruction_type: 'RemoveDependency',
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
        <h3 className="text-sm font-semibold text-gray-200 mb-1">Dependencies</h3>
        <p className="text-xs text-gray-400">
          Dependencies declare that one component reaches into another's public
          surface. Changes queue as <code>AddDependency</code> /{' '}
          <code>RemoveDependency</code> instructions — apply them from the
          Pending Changes panel. Adding an edge that would close a cycle is
          rejected by the apply handler with the cycle path highlighted.
        </p>
      </section>

      <section className="rounded border border-gray-700 bg-gray-950 p-3 space-y-2">
        <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide">
          Add dependency
        </h4>
        <div className="flex flex-wrap items-baseline gap-2 text-sm">
          <label className="flex items-baseline gap-1">
            <span className="text-gray-400">From</span>
            <select
              className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-100"
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
            >
              <option value="">— select source —</option>
              {comps.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} {compLevelSuffix(c)}
                </option>
              ))}
            </select>
          </label>
          <span className="text-gray-500">depends on</span>
          <label className="flex items-baseline gap-1">
            <span className="text-gray-400">To</span>
            <select
              className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-100"
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
            >
              <option value="">— select target —</option>
              {comps.map((c) => (
                <option key={c.id} value={c.id} disabled={c.id === sourceId}>
                  {c.name} {compLevelSuffix(c)}
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
        {sourceId && targetId && sourceId === targetId && (
          <p className="text-xs text-amber-300">Source and target must differ.</p>
        )}
        {sourceId && targetId && alreadyExists(sourceId, targetId) && (
          <p className="text-xs text-gray-400">
            This dependency already exists.
          </p>
        )}
      </section>

      <section>
        <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide mb-2">
          Existing dependencies ({deps.length})
        </h4>
        {deps.length === 0 ? (
          <p className="text-sm text-gray-400">
            No dependency edges yet. Sysarch seeds them at approval time;
            comparch can add more in its <code>&lt;dependencies&gt;</code>{' '}
            section.
          </p>
        ) : (
          <ul className="space-y-1 text-sm">
            {deps.map((e) => {
              const src = compById.get(e.source_id);
              const tgt = compById.get(e.target_id);
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

function compLevelSuffix(c: { parent_id: string | null }) {
  return c.parent_id ? '(sub)' : '(top)';
}
