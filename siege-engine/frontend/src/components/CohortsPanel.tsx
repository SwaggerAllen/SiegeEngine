import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  generateExplorationSample,
  generateFullCorpus,
  listCohorts,
  patchCohort,
  regenerateCohort,
  type Cohort,
} from '../api/cohorts';

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
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const archiveMutation = useMutation({
    mutationFn: () => patchCohort(projectId, cohort.id, { archived: !cohort.archived }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cohorts', projectId] });
    },
  });

  const regenMutation = useMutation({
    mutationFn: (mode: 'fresh' | 'review') => regenerateCohort(projectId, cohort.id, mode),
    onSuccess: (result) => {
      const skipText = result.scopes_skipped.length
        ? ` (${result.scopes_skipped.length} skipped)`
        : '';
      setStatusMsg(
        `Started ${result.mode} cycle: batch ${result.batch_id.slice(0, 14)}…, ` +
          `${result.scopes_succeeded}/${result.scopes_total} scopes enqueued${skipText}.`,
      );
    },
    onError: (err: unknown) => {
      setStatusMsg(`Regenerate failed: ${err instanceof Error ? err.message : String(err)}`);
    },
  });

  const isRegenerating = regenMutation.isPending;

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
            {cohort.comp_ids.length} comp{cohort.comp_ids.length === 1 ? '' : 's'}
            {cohort.created_at && (
              <> · created {cohort.created_at.slice(0, 10)}</>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!cohort.archived && cohort.comp_ids.length > 0 && (
            <>
              <button
                type="button"
                onClick={() => regenMutation.mutate('review')}
                disabled={isRegenerating}
                title="Regenerate cohort subs with prior_review_text feeding forward (self-review iteration)"
                className="px-2 py-1 text-xs rounded bg-blue-700 hover:bg-blue-600 text-white disabled:opacity-40"
                data-testid={`cohort-row-${cohort.id}-regen-review`}
              >
                {isRegenerating ? 'Starting…' : 'New cycle (review)'}
              </button>
              <button
                type="button"
                onClick={() => regenMutation.mutate('fresh')}
                disabled={isRegenerating}
                title="Regenerate cohort subs from scratch (wipe + fresh gen, no prior context)"
                className="px-2 py-1 text-xs rounded border border-amber-800 text-amber-200 hover:bg-amber-950 disabled:opacity-40"
                data-testid={`cohort-row-${cohort.id}-regen-fresh`}
              >
                {isRegenerating ? 'Starting…' : 'New cycle (fresh)'}
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="px-2 py-1 text-xs rounded border border-gray-700 text-gray-300 hover:bg-gray-800"
          >
            {expanded ? 'Hide comps' : 'Show comps'}
          </button>
          <button
            type="button"
            onClick={() => archiveMutation.mutate()}
            disabled={archiveMutation.isPending}
            className="px-2 py-1 text-xs rounded border border-gray-700 text-gray-300 hover:bg-gray-800 disabled:opacity-40"
          >
            {cohort.archived ? 'Unarchive' : 'Archive'}
          </button>
        </div>
      </div>
      {statusMsg && (
        <div className="text-xs text-emerald-400" data-testid={`cohort-row-${cohort.id}-message`}>
          {statusMsg}
        </div>
      )}
      {expanded && (
        <ul className="text-[11px] font-mono text-gray-400 ml-3 list-disc">
          {cohort.comp_ids.map((id) => (
            <li key={id}>{id}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

function SubcompCampaignActions({
  projectId,
  cohorts,
}: {
  projectId: string;
  cohorts: Cohort[];
}) {
  const [explorationCount, setExplorationCount] = useState(5);
  const [fullCorpusConfirm, setFullCorpusConfirm] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const activeCohort = cohorts.find((c) => !c.archived && c.tier === 'comparch');
  const explorationMutation = useMutation({
    mutationFn: () =>
      generateExplorationSample(projectId, {
        count: explorationCount,
        exclude_cohort_id: activeCohort?.id,
      }),
    onSuccess: (result) => {
      setStatusMsg(
        `Exploration sample: ${result.picked_comp_ids.length} new comps, ` +
          `${result.scopes_succeeded}/${result.scopes_total} subs enqueued ` +
          `(batch ${result.batch_id.slice(0, 14)}…).`,
      );
    },
    onError: (err: unknown) => {
      setStatusMsg(`Exploration sample failed: ${err instanceof Error ? err.message : String(err)}`);
    },
  });
  const fullCorpusMutation = useMutation({
    mutationFn: () => generateFullCorpus(projectId),
    onSuccess: (result) => {
      setFullCorpusConfirm(false);
      setStatusMsg(
        `Full corpus: ${result.scopes_succeeded}/${result.scopes_total} subs enqueued ` +
          `(batch ${result.batch_id.slice(0, 14)}…).`,
      );
    },
    onError: (err: unknown) => {
      setStatusMsg(`Full corpus failed: ${err instanceof Error ? err.message : String(err)}`);
    },
  });

  const isBusy = explorationMutation.isPending || fullCorpusMutation.isPending;

  return (
    <div className="rounded border border-gray-800 bg-gray-950/40 p-3 text-xs space-y-2">
      <div className="font-medium text-gray-200">Subcomparch campaign</div>
      <div className="flex flex-wrap items-center gap-2">
        <label>
          Exploration count:{' '}
          <input
            type="number"
            min={1}
            max={50}
            value={explorationCount}
            onChange={(e) => setExplorationCount(Math.max(1, Number(e.target.value) || 1))}
            className="w-12 bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-gray-200"
          />
        </label>
        <button
          type="button"
          onClick={() => explorationMutation.mutate()}
          disabled={isBusy}
          title="Pick N random comps not in the active cohort and not previously sampled, regenerate their subs under one batch"
          className="px-2 py-1 rounded border border-blue-800 text-blue-200 hover:bg-blue-950 disabled:opacity-40"
          data-testid="cohorts-exploration-sample"
        >
          {explorationMutation.isPending ? 'Sampling…' : 'Exploration sample'}
        </button>
        {fullCorpusConfirm ? (
          <>
            <button
              type="button"
              onClick={() => fullCorpusMutation.mutate()}
              disabled={isBusy}
              className="px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-white disabled:opacity-40"
              data-testid="cohorts-full-corpus-confirm"
            >
              {fullCorpusMutation.isPending
                ? 'Regenerating all…'
                : 'Confirm: regenerate every subcomp'}
            </button>
            <button
              type="button"
              onClick={() => setFullCorpusConfirm(false)}
              disabled={isBusy}
              className="px-2 py-1 rounded border border-gray-700 text-gray-300 hover:bg-gray-800 disabled:opacity-40"
            >
              Cancel
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setFullCorpusConfirm(true)}
            disabled={isBusy}
            title="Regenerate every existing subcomp from scratch — final-sweep escape hatch"
            className="px-2 py-1 rounded border border-red-900 text-red-300 hover:bg-red-950 disabled:opacity-40"
            data-testid="cohorts-full-corpus"
          >
            Full corpus
          </button>
        )}
      </div>
      {statusMsg && (
        <div className="text-emerald-400" data-testid="cohorts-campaign-message">
          {statusMsg}
        </div>
      )}
    </div>
  );
}
