import { useMemo, useState } from 'react';
import type { Instruction } from '../../api/queue';
import { useProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useEnqueueInstructionMutation } from '../../hooks/mutations/useQueueMutations';
import { describeApiError } from '../../lib/describeApiError';
import { DomainParentGraphView } from './DomainParentGraphView';

interface Props {
  projectId: string;
}

/**
 * Phase 11 Structured UI #6 — domain-parent editor.
 *
 * Primary view: Cytoscape graph (``DomainParentGraphView``) —
 * tap presentational source → tap domain target → Queue add.
 * Enforces the 1-2 domain-parents-per-presentational cap
 * client-side. Fallback: the original list-based editor
 * preserved below for accessibility.
 */
export function DomainParentEditorPanel({ projectId }: Props) {
  const { data, error, isLoading } = useProjectStructure(projectId);
  const [view, setView] = useState<'graph' | 'list'>('graph');

  const topLevelComps = useMemo(
    () =>
      (data?.nodes ?? [])
        .filter((n) => n.tier === 'comp' && n.parent_id === null)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [data],
  );
  const domainParentEdges = useMemo(
    () => (data?.edges ?? []).filter((e) => e.edge_type === 'domain_parent'),
    [data],
  );

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
    <div className="flex flex-col h-full">
      <header className="flex items-baseline gap-3 border-b border-gray-800 px-4 py-2">
        <h3 className="text-sm font-semibold text-gray-200">Domain parents</h3>
        <p className="text-xs text-gray-400 flex-1">
          {view === 'graph'
            ? 'Tap a presentational component to pick a source, then tap a domain comp to stage a domain-parent edge. Cap: 1-2 domain parents per presentational.'
            : 'Every domain-parent edge in the project. Add via the form; the list is the accessibility fallback for the graph view.'}
        </p>
        <ViewToggle view={view} onChange={setView} />
      </header>
      <div className="flex-1 min-h-0 overflow-auto">
        {view === 'graph' ? (
          <DomainParentGraphView
            projectId={projectId}
            topLevelComps={topLevelComps}
            domainParentEdges={domainParentEdges}
          />
        ) : (
          <DomainParentListView projectId={projectId} />
        )}
      </div>
    </div>
  );
}

function ViewToggle({
  view,
  onChange,
}: {
  view: 'graph' | 'list';
  onChange: (v: 'graph' | 'list') => void;
}) {
  const btn = (val: 'graph' | 'list', label: string) => (
    <button
      type="button"
      onClick={() => onChange(val)}
      className={`px-2 py-0.5 text-xs ${
        view === val
          ? 'bg-gray-700 text-white'
          : 'text-gray-400 hover:text-gray-200'
      }`}
      data-testid={`dp-view-${val}`}
      aria-pressed={view === val}
    >
      {label}
    </button>
  );
  return (
    <div
      role="group"
      aria-label="Domain-parent view toggle"
      className="flex rounded border border-gray-700 overflow-hidden"
    >
      {btn('graph', 'Graph')}
      {btn('list', 'List')}
    </div>
  );
}

// ── List fallback (preserved from the pre-graph MVP) ───────────────

function DomainParentListView({ projectId }: { projectId: string }) {
  const { data } = useProjectStructure(projectId);
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

  return (
    <div className="p-4 max-w-3xl space-y-6">
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
