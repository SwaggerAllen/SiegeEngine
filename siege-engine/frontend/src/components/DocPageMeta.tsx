import { formatDateTimeSec } from '../utils/dateFormat';

export interface DocPageLastGenerationJob {
  /** Raw status from the Job row — preserves cancelled (which the
   * 4-state ``generation_status`` collapses into ``idle``) so the
   * doc-page header can surface "last gen: cancelled" explicitly. */
  status: string;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
}

interface Props {
  lastGenerationJob: DocPageLastGenerationJob | null;
  lastContentUpdatedAt: string | null;
}

/**
 * Two-line meta block that sits under a doc-page heading. Surfaces:
 *
 * 1. Last generation job for this doc — preserves the raw status
 *    (running / queued / completed / failed / cancelled) so a
 *    cancelled regen is visible at a glance, plus the timestamp
 *    and any error message.
 * 2. Last time the approved content for this node actually
 *    landed (most recent ``NodeContentUpdated`` event) — so
 *    users can tell whether the content they're reading is fresh
 *    or stale.
 *
 * Both fields are independently nullable; the component renders
 * nothing when both are missing (covers brand-new bootstrap nodes
 * that haven't generated once yet).
 */
export function DocPageMeta({ lastGenerationJob, lastContentUpdatedAt }: Props) {
  const statusToneClass = (() => {
    if (!lastGenerationJob) return 'text-gray-400';
    switch (lastGenerationJob.status) {
      case 'cancelled':
        return 'text-amber-400';
      case 'failed':
        return 'text-red-400';
      case 'running':
      case 'queued':
        return 'text-blue-400';
      case 'completed':
        return 'text-emerald-400';
      default:
        return 'text-gray-300';
    }
  })();
  const jobTimestamp =
    lastGenerationJob?.completed_at ?? lastGenerationJob?.created_at ?? null;
  return (
    <div
      className="rounded border border-gray-800 bg-gray-900/40 px-3 py-2 text-sm text-gray-300 space-y-1"
      data-testid="doc-page-meta"
    >
      {lastGenerationJob && jobTimestamp ? (
        <div>
          <span className="text-gray-500">Last generation:</span>{' '}
          <span className={statusToneClass}>{lastGenerationJob.status}</span>
          <span className="text-gray-500"> · {formatDateTimeSec(jobTimestamp)}</span>
          {(lastGenerationJob.status === 'cancelled' ||
            lastGenerationJob.status === 'failed') &&
            lastGenerationJob.error_message && (
              <span className="text-gray-500"> — {lastGenerationJob.error_message}</span>
            )}
        </div>
      ) : (
        <div className="text-gray-500">Last generation: no prior runs.</div>
      )}
      {lastContentUpdatedAt ? (
        <div>
          <span className="text-gray-500">Approved content last landed:</span>{' '}
          {formatDateTimeSec(lastContentUpdatedAt)}
        </div>
      ) : (
        <div className="text-gray-500">
          Approved content: never written for this node yet.
        </div>
      )}
    </div>
  );
}
