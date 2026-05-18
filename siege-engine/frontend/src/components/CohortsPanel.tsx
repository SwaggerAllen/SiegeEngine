import { useMemo, useState } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import { listCohorts, type Cohort } from '../api/cohorts';
import {
  getTierReviewSummary,
  listBatches,
  type TierReviewSummary,
} from '../api/tierOps';
import { SamplerConfigEditor } from './SamplerConfigEditor';

interface Props {
  projectId: string;
}

/**
 * Cohort dashboard — list saved cohorts, drill into detail.
 *
 * Phase 3a ships this as a read-only inventory: see cohorts,
 * archive / unarchive, view comp lists. The action buttons
 * ("Start new cycle", "Resume current cycle", "Exploration sample"
 * etc.) land in Phase 3b once the regenerate / exploration
 * endpoints exist.
 */
export function CohortsPanel({ projectId }: Props) {
  const [showArchived, setShowArchived] = useState(false);
  const { data: cohorts, isLoading, isError } = useQuery({
    queryKey: ['cohorts', projectId],
    queryFn: () => listCohorts(projectId),
  });

  const filtered = useMemo(() => {
    if (!cohorts) return [] as Cohort[];
    return showArchived ? cohorts : cohorts.filter((c) => !c.archived);
  }, [cohorts, showArchived]);

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      <header>
        <h2 className="text-lg font-semibold">Cohorts</h2>
        <p className="text-xs text-gray-400 mt-1">
          Saved samples of comp IDs to drive iteration campaigns at the next tier
          down. Pick comps from the per-tier structure summary, save as a cohort,
          and use it to A/B prompt changes against a fixed baseline.
        </p>
      </header>
      <SubcompCampaignActions projectId={projectId} cohorts={cohorts ?? []} />
      <SamplerConfigEditor projectId={projectId} tier="comparch" />
      <div className="text-xs">
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />
          <span className="text-gray-400">Show archived</span>
        </label>
      </div>
      {isLoading && <div className="text-xs text-gray-500 italic">Loading cohorts…</div>}
      {isError && <div className="text-xs text-red-400">Failed to load cohorts</div>}
      {!isLoading && !isError && filtered.length === 0 && (
        <div className="text-xs text-gray-500 italic">
          No cohorts yet. Open a tier&apos;s structure summary, hit
          <span className="text-gray-300"> Select for cohort</span>, pick comps,
          and save.
        </div>
      )}
      {filtered.length > 0 && (
        <ul className="divide-y divide-gray-800 border border-gray-800 rounded">
          {filtered.map((c) => (
            <CohortRow key={c.id} projectId={projectId} cohort={c} />
          ))}
        </ul>
      )}
    </div>
  );
}

function CohortRow({ projectId, cohort }: { projectId: string; cohort: Cohort }) {
  const [expanded, setExpanded] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  // Phase 3 migration: cohort archive + cycle (review/fresh) regen
  // moved to Claude Code skills. The dashboard renders the saved
  // cohort metadata + cycle history; mutations no longer fire from
  // the browser.
  // TODO Phase 3: deep-link each disabled button to its CC skill:
  //   - Archive             → /archive-cohort <cohort_id>
  //   - New cycle (review)  → /cohort-cycle-review <cohort_id>
  //   - New cycle (fresh)   → /cohort-cycle-fresh <cohort_id> <expl_count>
  return (
    <li className="px-4 py-3 flex flex-col gap-2" data-testid={`cohort-row-${cohort.id}`}>
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-gray-100">
            {cohort.name}{' '}
            <span className="text-xs text-gray-500">
              · {cohort.tier} · v{cohort.version}
              {cohort.archived ? ' · archived' : ''}
            </span>
          </div>
          <div className="text-xs text-gray-500 mt-0.5">
            {cohort.comp_ids.length} canonical
            {cohort.experimental_comp_ids.length > 0 && (
              <> · {cohort.experimental_comp_ids.length} experimental</>
            )}
            {cohort.created_at && (
              <> · created {cohort.created_at.slice(0, 10)}</>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!cohort.archived && cohort.comp_ids.length > 0 && (
            <button
              type="button"
              disabled
              className="px-2 py-1 text-xs rounded border border-blue-800 text-blue-200/60 cursor-not-allowed"
              title="New cycle moved to Claude Code — invoke /cohort-cycle-review or /cohort-cycle-fresh there"
              data-testid={`cohort-row-${cohort.id}-regen-cycle`}
            >
              Open in Claude Code · New cycle
            </button>
          )}
          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            className="px-2 py-1 text-xs rounded border border-gray-700 text-gray-300 hover:bg-gray-800"
          >
            {showHistory ? 'Hide cycles' : 'Cycle history'}
          </button>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="px-2 py-1 text-xs rounded border border-gray-700 text-gray-300 hover:bg-gray-800"
          >
            {expanded ? 'Hide comps' : 'Show comps'}
          </button>
          <button
            type="button"
            disabled
            className="px-2 py-1 text-xs rounded border border-gray-700 text-gray-400 cursor-not-allowed"
            title="Archive moved to Claude Code — invoke /archive-cohort there"
            data-testid={`cohort-row-${cohort.id}-archive`}
          >
            {cohort.archived ? 'Unarchive · CC' : 'Archive · CC'}
          </button>
        </div>
      </div>
      {expanded && (
        <ul className="text-[11px] font-mono text-gray-400 ml-3 list-disc">
          {cohort.comp_ids.map((id) => (
            <li key={id}>{id}</li>
          ))}
        </ul>
      )}
      {showHistory && <CycleHistory projectId={projectId} cohort={cohort} />}
    </li>
  );
}

function CycleHistory({ projectId, cohort }: { projectId: string; cohort: Cohort }) {
  const { data: batches, isLoading } = useQuery({
    queryKey: ['cohortBatches', projectId, cohort.id],
    queryFn: () =>
      listBatches(projectId, {
        cohort_id: cohort.id,
        op_type: 'cohort_regenerate',
        limit: 25,
      }),
  });
  // Per-batch review summary for the target tier (subcomparch
  // for a comparch cohort). Parallel fetches via useQueries so the
  // table renders incrementally as each summary arrives.
  const targetTier = 'subcomparch';
  const summaryQueries = useQueries({
    queries: (batches ?? []).map((b) => ({
      queryKey: ['tierReviewSummary', projectId, targetTier, b.id],
      queryFn: () => getTierReviewSummary(projectId, targetTier as 'subcomparch', b.id),
    })),
  });

  if (isLoading) {
    return <div className="ml-3 text-xs text-gray-500 italic">Loading cycles…</div>;
  }
  if (!batches || batches.length === 0) {
    return <div className="ml-3 text-xs text-gray-500 italic">No cycles yet.</div>;
  }

  // Newest-first order. Score deltas computed per-mode-pair: walk
  // backwards in time and look for the prior batch with the same
  // mode; mean-score delta against that one.
  const rows = batches.map((b, idx) => {
    const summary: TierReviewSummary | undefined = summaryQueries[idx]?.data;
    return { batch: b, summary };
  });
  const meanByIdx = rows.map((r) => r.summary?.score_stats?.mean ?? null);

  return (
    <div
      className="ml-3 mt-2 rounded border border-gray-800 bg-gray-950/40 p-2 text-[11px]"
      data-testid={`cohort-row-${cohort.id}-cycle-history`}
    >
      <div className="text-gray-400 mb-1">Cycles (newest first)</div>
      <table className="w-full">
        <thead>
          <tr className="text-left text-gray-500">
            <th className="px-1 py-0.5">Mode</th>
            <th className="px-1 py-0.5">Started</th>
            <th className="px-1 py-0.5">Reviewed</th>
            <th className="px-1 py-0.5">Mean score</th>
            <th className="px-1 py-0.5">Δ vs prior same-mode</th>
            <th className="px-1 py-0.5">Batch</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ batch, summary }, idx) => {
            const mode = (batch.params?.mode as string) ?? '?';
            const mean = summary?.score_stats?.mean ?? null;
            const reviewedCount = summary?.reviewed_count ?? 0;
            const totalCount = summary?.draft_count ?? 0;
            // Find prior batch (higher idx = older) with the same
            // mode for delta computation.
            let delta: number | null = null;
            for (let j = idx + 1; j < rows.length; j += 1) {
              if (rows[j].batch.params?.mode === mode) {
                const priorMean = meanByIdx[j];
                if (mean !== null && priorMean !== null) {
                  delta = mean - priorMean;
                }
                break;
              }
            }
            return (
              <tr key={batch.id} className="border-t border-gray-900">
                <td className="px-1 py-0.5">
                  <ModeBadge mode={mode} />
                </td>
                <td className="px-1 py-0.5 font-mono text-gray-400">
                  {batch.started_at?.slice(0, 16) ?? '—'}
                </td>
                <td className="px-1 py-0.5 text-gray-300">
                  {reviewedCount}/{totalCount}
                </td>
                <td className="px-1 py-0.5 font-mono text-gray-200">
                  {mean !== null ? mean.toFixed(1) : '—'}
                </td>
                <td className="px-1 py-0.5 font-mono">
                  <DeltaCell value={delta} />
                </td>
                <td className="px-1 py-0.5 font-mono text-gray-500" title={batch.id}>
                  {batch.id.slice(0, 14)}…
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ModeBadge({ mode }: { mode: string }) {
  if (mode === 'fresh') {
    return (
      <span className="px-1.5 py-0.5 rounded bg-amber-900 text-amber-200">fresh</span>
    );
  }
  if (mode === 'review') {
    return (
      <span className="px-1.5 py-0.5 rounded bg-blue-900 text-blue-200">review</span>
    );
  }
  return <span className="text-gray-500">{mode}</span>;
}

function DeltaCell({ value }: { value: number | null }) {
  if (value === null) return <span className="text-gray-600">—</span>;
  if (Math.abs(value) < 0.05) return <span className="text-gray-400">±0.0</span>;
  if (value > 0) return <span className="text-emerald-400">▲ {value.toFixed(1)}</span>;
  return <span className="text-red-400">▼ {Math.abs(value).toFixed(1)}</span>;
}

function SubcompCampaignActions({
  cohorts,
}: {
  projectId: string;
  cohorts: Cohort[];
}) {
  // Active cohort drives the campaign tier — full-corpus runs at
  // the active cohort's tier on the backend.
  const activeCohort = cohorts.find((c) => !c.archived);
  const campaignTier = activeCohort?.tier ?? 'comparch';

  // TODO Phase 3: deep-link Full corpus to /full-corpus <tier> in CC.
  return (
    <div className="rounded border border-gray-800 bg-gray-950/40 p-3 text-xs space-y-2">
      <div className="font-medium text-gray-200">Campaign actions ({campaignTier})</div>
      <div className="text-gray-500">
        Experimental set is managed by the cohort's New cycle skill in
        Claude Code — see the per-row Open-in-CC fallback. Review iterates
        the working set without touching either.
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled
          className="px-2 py-1 rounded border border-red-900 text-red-300/60 cursor-not-allowed"
          title={`Full corpus moved to Claude Code — invoke /full-corpus ${campaignTier} there`}
          data-testid="cohorts-full-corpus"
        >
          Open in Claude Code · Full corpus
        </button>
      </div>
    </div>
  );
}
