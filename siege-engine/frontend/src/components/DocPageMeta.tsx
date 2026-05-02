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
  if (!lastGenerationJob && !lastContentUpdatedAt) return null;
  const statusToneClass = (() => {
    if (!lastGenerationJob) return 'text-gray-500';
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
        return 'text-gray-400';
    }
  })();
  const jobTimestamp =
    lastGenerationJob?.completed_at ?? lastGenerationJob?.created_at ?? null;
  return (
    <div className="text-xs text-gray-500 space-y-0.5" data-testid="doc-page-meta">
      {lastGenerationJob && jobTimestamp && (
        <div>
          Last generation:{' '}
          <span className={statusToneClass}>{lastGenerationJob.status}</span>
          {' · '}
          {formatDateTimeSec(jobTimestamp)}
          {(lastGenerationJob.status === 'cancelled' ||
            lastGenerationJob.status === 'failed') &&
            lastGenerationJob.error_message && (
              <span className="text-gray-500"> — {lastGenerationJob.error_message}</span>
            )}
        </div>
      )}
      {lastContentUpdatedAt && (
        <div>Approved content last landed: {formatDateTimeSec(lastContentUpdatedAt)}</div>
      )}
    </div>
  );
}
