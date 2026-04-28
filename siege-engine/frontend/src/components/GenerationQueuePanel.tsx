import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import {
  type JobRow,
  type JobStatus,
  cancelJob,
  deleteJob,
  listJobs,
  reprioritizeJob,
} from '../api/jobs';
import { describeApiError } from '../lib/describeApiError';

const ACTIVE_STATUSES: JobStatus[] = ['queued', 'running'];
const ALL_STATUSES: JobStatus[] = [
  'running',
  'queued',
  'failed',
  'cancelled',
  'completed',
];

/**
 * Generation queue panel — view + manage the project's job rows.
 *
 * Distinct from the Phase 11 "Pending Changes" panel (which is the
 * user-authored instruction queue). This panel surfaces the
 * generation queue: every ``v2.*`` background job the worker is
 * processing for the project.
 *
 * Affordances:
 *   - cancel (queued or running)
 *   - reprioritize (queued only, +/- bumps in 5-priority steps)
 *   - delete (terminal rows, or queued via cancel-then-delete)
 *
 * Refresh is a 2s poll while any active job exists; otherwise 10s.
 */
export function GenerationQueuePanel({ projectId }: { projectId: string }) {
  const [activeOnly, setActiveOnly] = useState(true);
  const queryClient = useQueryClient();

  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['generation-queue', projectId, activeOnly],
    queryFn: () =>
      listJobs(projectId, {
        status: activeOnly ? ACTIVE_STATUSES : ALL_STATUSES,
        limit: 200,
      }),
    refetchInterval: (query) => {
      const counts = query.state.data?.status_counts ?? {};
      const active = (counts.running ?? 0) + (counts.queued ?? 0);
      return active > 0 ? 2000 : 10000;
    },
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['generation-queue', projectId] });

  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => cancelJob(projectId, jobId),
    onSuccess: invalidate,
  });

  const reprioritizeMutation = useMutation({
    mutationFn: ({ jobId, priority }: { jobId: string; priority: number }) =>
      reprioritizeJob(projectId, jobId, priority),
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: (jobId: string) => deleteJob(projectId, jobId),
    onSuccess: invalidate,
  });

  const counts = data?.status_counts ?? {};
  const activeCount = (counts.running ?? 0) + (counts.queued ?? 0);

  const sortedJobs = useMemo(() => data?.jobs ?? [], [data?.jobs]);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      <header className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-lg font-semibold">Generation Queue</h2>
        <span className="text-xs text-gray-500">
          {activeCount} active · {data?.total_returned ?? 0} shown
        </span>
        <div className="ml-auto flex items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-gray-300">
            <input
              type="checkbox"
              checked={activeOnly}
              onChange={(e) => setActiveOnly(e.target.checked)}
            />
            Active only
          </label>
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="px-3 py-1 text-xs rounded border border-gray-700 text-gray-300 hover:bg-gray-800 disabled:opacity-40"
          >
            {isFetching ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </header>

      {!activeOnly && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs">
          {ALL_STATUSES.map((s) => (
            <Stat key={s} label={s} value={counts[s] ?? 0} />
          ))}
        </div>
      )}

      {isLoading && (
        <div className="text-sm text-gray-400">Loading queue…</div>
      )}
      {error && (
        <div className="text-sm text-red-400">
          {describeApiError(error, 'Failed to load queue')}
        </div>
      )}
      {!isLoading && !error && sortedJobs.length === 0 && (
        <div className="text-sm text-gray-500 italic">
          {activeOnly
            ? 'No active jobs. Toggle "Active only" off to see history.'
            : 'No jobs for this project yet.'}
        </div>
      )}

      {sortedJobs.length > 0 && (
        <div className="overflow-x-auto border border-gray-800 rounded">
          <table className="w-full text-xs font-mono">
            <thead className="bg-gray-900/40 text-gray-500 text-left">
              <tr>
                <th className="px-3 py-2 font-normal">Status</th>
                <th className="px-3 py-2 font-normal">Type</th>
                <th className="px-3 py-2 font-normal">Scope</th>
                <th className="px-3 py-2 font-normal">Pri</th>
                <th className="px-3 py-2 font-normal">Created</th>
                <th className="px-3 py-2 font-normal">Retry</th>
                <th className="px-3 py-2 font-normal text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sortedJobs.map((job) => (
                <JobRowView
                  key={job.id}
                  job={job}
                  onCancel={() => cancelMutation.mutate(job.id)}
                  onReprioritize={(priority) =>
                    reprioritizeMutation.mutate({ jobId: job.id, priority })
                  }
                  onDelete={() => deleteMutation.mutate(job.id)}
                  busy={
                    cancelMutation.isPending ||
                    reprioritizeMutation.isPending ||
                    deleteMutation.isPending
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-gray-800 bg-gray-900/40 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-gray-500">{label}</div>
      <div className="text-base font-mono text-gray-100 tabular-nums">{value}</div>
    </div>
  );
}

function JobRowView({
  job,
  onCancel,
  onReprioritize,
  onDelete,
  busy,
}: {
  job: JobRow;
  onCancel: () => void;
  onReprioritize: (priority: number) => void;
  onDelete: () => void;
  busy: boolean;
}) {
  const isActive = job.status === 'queued' || job.status === 'running';
  const isTerminal =
    job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled';

  return (
    <tr className="border-t border-gray-800/60 align-top">
      <td className="px-3 py-2">
        <StatusPill status={job.status} />
      </td>
      <td className="px-3 py-2 text-gray-300">{job.job_type}</td>
      <td className="px-3 py-2 text-gray-400">
        <ScopeCell payload={job.payload} />
        {job.error_message && (
          <div className="text-amber-400 mt-1 whitespace-pre-wrap break-words max-w-md">
            {job.error_message}
          </div>
        )}
      </td>
      <td className="px-3 py-2 text-gray-300 tabular-nums">
        {job.priority}
        {job.status === 'queued' && (
          <span className="ml-2 inline-flex gap-1">
            <button
              type="button"
              onClick={() => onReprioritize(Math.max(0, job.priority - 5))}
              disabled={busy || job.priority <= 0}
              className="px-1 rounded border border-gray-700 text-gray-300 hover:bg-gray-800 disabled:opacity-40"
              title="Bump priority up (lower number wins)"
            >
              ▲
            </button>
            <button
              type="button"
              onClick={() => onReprioritize(Math.min(100, job.priority + 5))}
              disabled={busy || job.priority >= 100}
              className="px-1 rounded border border-gray-700 text-gray-300 hover:bg-gray-800 disabled:opacity-40"
              title="Bump priority down"
            >
              ▼
            </button>
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-gray-500">{formatTime(job.created_at)}</td>
      <td className="px-3 py-2 text-gray-400 tabular-nums">
        {job.retry_count}/{job.max_retries}
      </td>
      <td className="px-3 py-2 text-right space-x-1 whitespace-nowrap">
        {isActive && (
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="px-2 py-1 rounded border border-amber-800 text-amber-300 hover:bg-amber-950 disabled:opacity-40"
          >
            Cancel
          </button>
        )}
        {isTerminal && (
          <button
            type="button"
            onClick={onDelete}
            disabled={busy}
            className="px-2 py-1 rounded border border-gray-700 text-gray-300 hover:bg-gray-800 disabled:opacity-40"
          >
            Delete
          </button>
        )}
      </td>
    </tr>
  );
}

function StatusPill({ status }: { status: string }) {
  const colour =
    status === 'running'
      ? 'bg-blue-900/60 text-blue-200'
      : status === 'queued'
        ? 'bg-gray-800 text-gray-200'
        : status === 'failed'
          ? 'bg-red-900/60 text-red-200'
          : status === 'cancelled'
            ? 'bg-amber-900/60 text-amber-200'
            : 'bg-emerald-900/40 text-emerald-200';
  return (
    <span className={`px-2 py-0.5 rounded text-[10px] uppercase tracking-wider ${colour}`}>
      {status}
    </span>
  );
}

function ScopeCell({ payload }: { payload: Record<string, unknown> }) {
  const interesting = ['component_id', 'sub_id', 'owner_id', 'node_id', 'draft_id', 'ref_id'];
  const parts: string[] = [];
  for (const key of interesting) {
    const v = payload[key];
    if (typeof v === 'string' && v) {
      parts.push(`${key}=${v}`);
    }
  }
  if (parts.length === 0) return <span className="text-gray-600">—</span>;
  return <span className="break-all">{parts.join(' · ')}</span>;
}

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return iso;
  }
}
