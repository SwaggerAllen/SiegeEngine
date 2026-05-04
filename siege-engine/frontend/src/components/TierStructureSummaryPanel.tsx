import { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getTierStructureSummary,
  type StructureTierName,
  type TierStructureSummary,
  type StructureNodeRow,
} from '../api/tierOps';
import { autoSuggestCohort, createCohort } from '../api/cohorts';

interface Props {
  projectId: string;
  tier: StructureTierName;
}

// Tiers that support cohort selection. Currently only comparch
// is wired through; other tiers can opt in by adding their slug
// here once the campaign workflow extends to them.
const COHORT_SELECTABLE_TIERS: StructureTierName[] = ['comparch'];

/**
 * Read-only per-tier structure-summary dashboard. Surfaces what the
 * tier currently *contains* — counts, distributions, kind/foundation
 * ratios, multi-owner prevalence, content-presence — so the user
 * can scan the corpus shape before picking a sample / cohort.
 *
 * Renders generically off the backend's `{per_node, aggregate}`
 * shape. Per-node columns come from the keys of the first row's
 * `metrics` dict; aggregate values are rendered as a key-value list
 * with distribution dicts expanded inline.
 */
export function TierStructureSummaryPanel({ projectId, tier }: Props) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['tierStructureSummary', projectId, tier],
    queryFn: () => getTierStructureSummary(projectId, tier),
  });

  if (isLoading) {
    return (
      <div
        className="text-xs text-gray-500 italic"
        data-testid={`tier-structure-summary-${tier}`}
      >
        Loading structure summary…
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="text-xs text-red-400" data-testid={`tier-structure-summary-${tier}`}>
        Failed to load structure summary
        {error instanceof Error ? `: ${error.message}` : ''}
      </div>
    );
  }
  return <SummaryBody projectId={projectId} summary={data} tier={tier} />;
}

function SummaryBody({
  projectId,
  summary,
  tier,
}: {
  projectId: string;
  summary: TierStructureSummary;
  tier: StructureTierName;
}) {
  const supportsCohort = COHORT_SELECTABLE_TIERS.includes(tier);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());

  const toggleSelectionMode = useCallback(() => {
    setSelectionMode((v) => !v);
  }, []);
  const toggleId = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);
  const replaceSelection = useCallback((ids: Iterable<string>) => {
    setSelected(new Set(ids));
  }, []);
  const clearSelection = useCallback(() => setSelected(new Set()), []);

  return (
    <div
      className="space-y-3 rounded border border-gray-800 bg-gray-950/40 p-3"
      data-testid={`tier-structure-summary-${tier}`}
    >
      <Header summary={summary} />
      {supportsCohort && (
        <CohortSelectionBar
          projectId={projectId}
          tier={tier}
          summary={summary}
          selectionMode={selectionMode}
          toggleSelectionMode={toggleSelectionMode}
          selected={selected}
          replaceSelection={replaceSelection}
          clearSelection={clearSelection}
        />
      )}
      <AggregateBlock aggregate={summary.aggregate} tier={tier} />
      {summary.per_node.length > 0 ? (
        <PerNodeTable
          rows={summary.per_node}
          tier={tier}
          selectionMode={selectionMode}
          selected={selected}
          toggleId={toggleId}
        />
      ) : (
        <div className="text-xs text-gray-500 italic">No nodes in this tier yet.</div>
      )}
    </div>
  );
}

function CohortSelectionBar({
  projectId,
  tier,
  summary,
  selectionMode,
  toggleSelectionMode,
  selected,
  replaceSelection,
  clearSelection,
}: {
  projectId: string;
  tier: StructureTierName;
  summary: TierStructureSummary;
  selectionMode: boolean;
  toggleSelectionMode: () => void;
  selected: Set<string>;
  replaceSelection: (ids: Iterable<string>) => void;
  clearSelection: () => void;
}) {
  const [targetSize, setTargetSize] = useState(8);
  const [cohortName, setCohortName] = useState('canonical');
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const suggestMutation = useMutation({
    mutationFn: () =>
      autoSuggestCohort(projectId, tier, { target_size: targetSize }),
    onSuccess: (result) => {
      replaceSelection(result.suggested_ids);
      setStatusMsg(
        `Suggested ${result.suggested_ids.length} comp${result.suggested_ids.length === 1 ? '' : 's'} (axes: ${result.axes_used.join(', ') || 'none'}).`,
      );
    },
    onError: (err: unknown) => {
      setStatusMsg(`Auto-suggest failed: ${err instanceof Error ? err.message : String(err)}`);
    },
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      createCohort(projectId, {
        tier,
        name: cohortName.trim() || 'canonical',
        comp_ids: Array.from(selected),
      }),
    onSuccess: (cohort) => {
      queryClient.invalidateQueries({ queryKey: ['cohorts', projectId] });
      setStatusMsg(`Saved cohort "${cohort.name}" (${cohort.comp_ids.length} comps).`);
      clearSelection();
      navigate(`/projects/${projectId}?node=:cohorts`);
    },
    onError: (err: unknown) => {
      setStatusMsg(`Save failed: ${err instanceof Error ? err.message : String(err)}`);
    },
  });

  if (!selectionMode) {
    return (
      <div className="flex items-center gap-2 text-xs">
        <button
          type="button"
          onClick={toggleSelectionMode}
          className="px-2 py-1 rounded border border-gray-700 text-gray-300 hover:bg-gray-800"
          data-testid={`tier-structure-summary-${tier}-enter-selection`}
        >
          Select for cohort
        </button>
        <span className="text-gray-500">
          Pick comps to save as a sampling cohort.
        </span>
      </div>
    );
  }

  const totalRows = summary.per_node.length;
  return (
    <div
      className="space-y-2 rounded border border-amber-900/60 bg-amber-950/20 p-2 text-xs"
      data-testid={`tier-structure-summary-${tier}-selection-bar`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-amber-300 font-medium">
          Selecting {selected.size}/{totalRows}
        </span>
        <label className="text-gray-400">
          Target size:{' '}
          <input
            type="number"
            min={1}
            max={Math.max(1, totalRows)}
            value={targetSize}
            onChange={(e) => setTargetSize(Math.max(1, Number(e.target.value) || 1))}
            className="w-12 bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-gray-200"
          />
        </label>
        <button
          type="button"
          onClick={() => suggestMutation.mutate()}
          disabled={suggestMutation.isPending}
          className="px-2 py-1 rounded border border-blue-800 text-blue-200 hover:bg-blue-950 disabled:opacity-40"
        >
          {suggestMutation.isPending ? 'Suggesting…' : 'Auto-suggest'}
        </button>
        <button
          type="button"
          onClick={clearSelection}
          disabled={selected.size === 0}
          className="px-2 py-1 rounded border border-gray-700 text-gray-300 hover:bg-gray-800 disabled:opacity-40"
        >
          Clear
        </button>
        <button
          type="button"
          onClick={toggleSelectionMode}
          className="px-2 py-1 rounded border border-gray-700 text-gray-300 hover:bg-gray-800"
        >
          Exit selection
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-gray-400">
          Cohort name:{' '}
          <input
            type="text"
            value={cohortName}
            onChange={(e) => setCohortName(e.target.value)}
            className="w-32 bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-gray-200"
          />
        </label>
        <button
          type="button"
          onClick={() => saveMutation.mutate()}
          disabled={selected.size === 0 || saveMutation.isPending}
          className="px-2 py-1 rounded bg-emerald-700 hover:bg-emerald-600 text-white disabled:opacity-40"
          data-testid={`tier-structure-summary-${tier}-save-cohort`}
        >
          {saveMutation.isPending ? 'Saving…' : 'Save selection as cohort'}
        </button>
      </div>
      {statusMsg && (
        <div className="text-amber-200/80">{statusMsg}</div>
      )}
    </div>
  );
}

function Header({ summary }: { summary: TierStructureSummary }) {
  return (
    <div className="text-xs text-gray-300">
      <span className="font-semibold text-gray-100">{summary.tier_name}</span>
      <span className="text-gray-500">
        {' '}
        — {summary.per_node.length} node{summary.per_node.length === 1 ? '' : 's'}
      </span>
    </div>
  );
}

function AggregateBlock({
  aggregate,
  tier,
}: {
  aggregate: Record<string, unknown>;
  tier: string;
}) {
  const entries = Object.entries(aggregate);
  if (entries.length === 0) return null;
  return (
    <dl
      className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-xs"
      data-testid={`tier-structure-summary-${tier}-aggregate`}
    >
      {entries.map(([key, value]) => (
        <AggregateEntry key={key} label={key} value={value} />
      ))}
    </dl>
  );
}

function AggregateEntry({ label, value }: { label: string; value: unknown }) {
  // Distribution dicts (count/min/median/mean/p90/max) get a
  // compact one-line render. Other values render as scalars.
  if (
    value !== null &&
    typeof value === 'object' &&
    'min' in (value as Record<string, unknown>) &&
    'max' in (value as Record<string, unknown>)
  ) {
    const dist = value as Record<string, unknown>;
    const count = formatScalar(dist.count);
    if (count === '0') {
      return (
        <div className="contents">
          <dt className="text-gray-500">{humanizeKey(label)}</dt>
          <dd className="col-span-1 sm:col-span-2 text-gray-400 italic">
            (no data)
          </dd>
        </div>
      );
    }
    return (
      <div className="contents">
        <dt className="text-gray-500">{humanizeKey(label)}</dt>
        <dd className="col-span-1 sm:col-span-2 text-gray-200 font-mono text-[11px]">
          n={count} · min={formatScalar(dist.min)} · med={formatScalar(dist.median)}{' '}
          · mean={formatScalar(dist.mean)} · p90={formatScalar(dist.p90)} · max=
          {formatScalar(dist.max)}
        </dd>
      </div>
    );
  }
  return (
    <div className="contents">
      <dt className="text-gray-500">{humanizeKey(label)}</dt>
      <dd className="text-gray-200 font-mono text-[11px]">{formatScalar(value)}</dd>
    </div>
  );
}

function PerNodeTable({
  rows,
  tier,
  selectionMode,
  selected,
  toggleId,
}: {
  rows: StructureNodeRow[];
  tier: string;
  selectionMode: boolean;
  selected: Set<string>;
  toggleId: (id: string) => void;
}) {
  // Column order: id + name first, then metric keys from the first
  // row in declaration order.
  const metricKeys = useMemo(() => Object.keys(rows[0]?.metrics ?? {}), [rows]);
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  const sortedRows = useMemo(() => {
    if (!sortKey) return rows;
    const out = [...rows];
    out.sort((a, b) => {
      const av = sortKey === '__name' ? a.name : (a.metrics[sortKey] ?? null);
      const bv = sortKey === '__name' ? b.name : (b.metrics[sortKey] ?? null);
      if (av === bv) return 0;
      // null/undefined sort last for asc, first for desc.
      if (av === null || av === undefined) return sortDir === 'asc' ? 1 : -1;
      if (bv === null || bv === undefined) return sortDir === 'asc' ? -1 : 1;
      if (typeof av === 'number' && typeof bv === 'number') {
        return sortDir === 'asc' ? av - bv : bv - av;
      }
      const as = String(av);
      const bs = String(bv);
      return sortDir === 'asc' ? as.localeCompare(bs) : bs.localeCompare(as);
    });
    return out;
  }, [rows, sortKey, sortDir]);

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  }

  return (
    <div
      className="overflow-x-auto"
      data-testid={`tier-structure-summary-${tier}-table`}
    >
      <table className="min-w-full text-[11px] border-collapse">
        <thead>
          <tr className="border-b border-gray-800 text-left">
            {selectionMode && <th className="px-2 py-1 w-6" aria-label="Select" />}
            <SortableTh
              label="Name"
              active={sortKey === '__name'}
              dir={sortDir}
              onClick={() => toggleSort('__name')}
            />
            {metricKeys.map((k) => (
              <SortableTh
                key={k}
                label={humanizeKey(k)}
                active={sortKey === k}
                dir={sortDir}
                onClick={() => toggleSort(k)}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row) => {
            const isSelected = selectionMode && selected.has(row.id);
            return (
              <tr
                key={row.id}
                className={`border-b border-gray-900 hover:bg-gray-900/40 ${
                  isSelected ? 'bg-amber-950/30' : ''
                }`}
                data-testid={`tier-structure-summary-${tier}-row-${row.id}`}
              >
                {selectionMode && (
                  <td className="px-2 py-1">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleId(row.id)}
                      data-testid={`tier-structure-summary-${tier}-select-${row.id}`}
                    />
                  </td>
                )}
                <td className="px-2 py-1 text-gray-200">
                  <div title={row.id}>{row.name}</div>
                </td>
                {metricKeys.map((k) => (
                  <td key={k} className="px-2 py-1 font-mono text-gray-300">
                    {formatScalar(row.metrics[k])}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SortableTh({
  label,
  active,
  dir,
  onClick,
}: {
  label: string;
  active: boolean;
  dir: 'asc' | 'desc';
  onClick: () => void;
}) {
  return (
    <th className="px-2 py-1 font-medium text-gray-400">
      <button
        type="button"
        onClick={onClick}
        className="hover:text-gray-200 inline-flex items-center gap-1"
      >
        {label}
        {active && <span className="text-amber-400">{dir === 'asc' ? '▲' : '▼'}</span>}
      </button>
    </th>
  );
}

function humanizeKey(key: string): string {
  // snake_case → Title Case for readability. Keep "id" / "p90" as-is.
  return key
    .split('_')
    .map((part) => {
      if (part === 'id') return 'ID';
      if (part === 'p90') return 'p90';
      return part.charAt(0).toUpperCase() + part.slice(1);
    })
    .join(' ');
}

function formatScalar(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? '✓' : '—';
  if (typeof value === 'number') {
    if (Number.isInteger(value)) return String(value);
    return value.toFixed(2);
  }
  return String(value);
}
