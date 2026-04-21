import { useMemo, useState } from 'react';
import type { Instruction } from '../../api/queue';
import { useProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useEnqueueInstructionMutation } from '../../hooks/mutations/useQueueMutations';
import { describeApiError } from '../../lib/describeApiError';
import { DependencyGraphView } from './DependencyGraphView';

interface Props {
  projectId: string;
}

/**
 * Phase 11 Structured UI #5 — dependency editor.
 *
 * Primary view: Cytoscape graph (``DependencyGraphView``) — tap
 * source → tap target → Queue add, with client-side cycle
 * blocking. Fallback: the original list-based editor preserved
 * below for accessibility, narrow widths, and screen readers.
 * Both views share the same ``useEnqueueInstructionMutation``
 * hook and instruction payloads.
 */
export function DependencyEditorPanel({ projectId }: Props) {
  const { data, error, isLoading } = useProjectStructure(projectId);
  const [view, setView] = useState<'graph' | 'list'>('graph');

  const topLevelComps = useMemo(
    () =>
      (data?.nodes ?? [])
        .filter((n) => n.tier === 'comp' && n.parent_id === null)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [data],
  );

  const depEdges = useMemo(
    () => (data?.edges ?? []).filter((e) => e.edge_type === 'dependency'),
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
        <h3 className="text-sm font-semibold text-gray-200">Dependencies</h3>
        <p className="text-xs text-gray-400 flex-1">
          {view === 'graph'
            ? 'Tap a component to pick it as source, then tap a target to stage a dependency. Dashed-red borders mark targets that would close a cycle.'
            : 'Every dependency edge in the project. Add new deps via the form. The graph view is an alternative; the list is the accessibility fallback.'}
        </p>
        <ViewToggle view={view} onChange={setView} />
      </header>
      <div className="flex-1 min-h-0 overflow-auto">
        {view === 'graph' ? (
          <DependencyGraphView
            projectId={projectId}
            topLevelComps={topLevelComps}
            depEdges={depEdges}
          />
        ) : (
          <DependencyListView projectId={projectId} />
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
      data-testid={`dep-view-${val}`}
      aria-pressed={view === val}
    >
      {label}
    </button>
  );
  return (
    <div
      role="group"
      aria-label="Dependency view toggle"
      className="flex rounded border border-gray-700 overflow-hidden"
    >
      {btn('graph', 'Graph')}
      {btn('list', 'List')}
    </div>
  );
}

// ── List fallback (preserved from the pre-graph MVP) ───────────────

function DependencyListView({ projectId }: { projectId: string }) {
  const { data } = useProjectStructure(projectId);
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

  return (
    <div className="p-4 max-w-3xl space-y-6">
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
          <p className="text-xs text-gray-400">This dependency already exists.</p>
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
                src && tgt ? `${src.name} → ${tgt.name}` : `${e.source_id} → ${e.target_id}`;
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
