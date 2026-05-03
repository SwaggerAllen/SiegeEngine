import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { listCohorts, patchCohort, type Cohort } from '../api/cohorts';

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
  const queryClient = useQueryClient();
  const archiveMutation = useMutation({
    mutationFn: () => patchCohort(projectId, cohort.id, { archived: !cohort.archived }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cohorts', projectId] });
    },
  });

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
