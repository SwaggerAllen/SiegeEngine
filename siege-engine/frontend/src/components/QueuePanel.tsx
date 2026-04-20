import { useState } from 'react';
import { renderInstruction, type QueueRow } from '../api/queue';
import { useQueueList } from '../hooks/queries/useQueueQueries';
import {
  useApplyQueueMutation,
  useDiscardPendingMutation,
} from '../hooks/mutations/useQueueMutations';
import { describeApiError } from '../lib/describeApiError';

interface Props {
  projectId: string;
}

/**
 * Phase 11 — pending-change queue panel.
 *
 * Lists queued instructions produced by the structured edit UIs,
 * along with running / recently-terminated history. Provides the
 * two lifecycle affordances: per-row discard (free undo before
 * apply) and bulk "Apply changes" (enqueues the single
 * ``v2.apply_instructions`` job that drains the queue in sequence).
 *
 * Four visual states, keyed off the row list:
 *
 *   - **Empty** — placeholder; nothing to act on.
 *   - **Queued** — list of instructions with per-row discard +
 *     footer actions (Apply N, Discard all).
 *   - **Running** — at least one row is in flight. Apply is
 *     disabled until the running rows terminate; the hook's
 *     ``refetchInterval`` keeps the state fresh every 2s.
 *   - **Failed** — at least one row flipped to failed; the
 *     error banner surfaces the message and blocks further
 *     apply until the user discards + re-queues.
 */
export function QueuePanel({ projectId }: Props) {
  const { data, error, isLoading } = useQueueList(projectId);
  const discardMutation = useDiscardPendingMutation(projectId);
  const applyMutation = useApplyQueueMutation(projectId);
  const [pendingDiscardSeq, setPendingDiscardSeq] = useState<number | null>(null);

  if (isLoading) {
    return (
      <div className="p-4 text-sm text-gray-400">Loading pending changes…</div>
    );
  }
  if (error) {
    return (
      <div className="p-4 max-w-md">
        <h3 className="text-sm font-semibold text-red-400">
          Failed to load pending changes
        </h3>
        <p className="text-xs text-gray-400 mt-1">
          {describeApiError(error, 'Unknown error')}
        </p>
      </div>
    );
  }
  if (!data) return null;

  const queued = data.rows.filter((r) => r.status === 'queued');
  const running = data.rows.filter((r) => r.status === 'running');
  const failed = data.rows.filter((r) => r.status === 'failed');
  const terminal = data.rows.filter(
    (r) => r.status === 'applied' || r.status === 'discarded' || r.status === 'failed',
  );

  const anyRunning = running.length > 0;
  const applyDisabled =
    queued.length === 0 ||
    anyRunning ||
    applyMutation.isPending ||
    discardMutation.isPending;

  if (data.rows.length === 0) {
    return (
      <div className="p-4 text-sm text-gray-400">
        <p className="font-semibold text-gray-300">Pending changes</p>
        <p className="mt-1">
          No queued instructions. Actions in the structured edit pages
          enqueue changes here; hit "Apply" to execute them in order.
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 max-w-2xl space-y-4">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-gray-200">
          Pending changes
          {queued.length > 0 && (
            <span className="ml-2 text-xs text-gray-400">
              ({queued.length} queued
              {anyRunning ? `, ${running.length} running` : ''}
              {failed.length > 0 ? `, ${failed.length} failed` : ''})
            </span>
          )}
        </h3>
      </div>

      {running.length > 0 && (
        <div className="rounded border border-amber-700 bg-amber-950/40 px-3 py-2 text-xs text-amber-200">
          Applying {running.length} instruction{running.length === 1 ? '' : 's'}…
        </div>
      )}

      {failed.length > 0 && (
        <div className="rounded border border-red-700 bg-red-950/40 px-3 py-2 text-xs text-red-200">
          <div className="font-semibold mb-1">
            Apply halted on sequence #{failed[0].sequence}
          </div>
          <div className="whitespace-pre-wrap text-red-100/80">
            {failed[0].error ?? 'Unknown failure'}
          </div>
          <div className="mt-1 text-red-300/80">
            Discard the failed row (or the whole queue) before retrying.
          </div>
        </div>
      )}

      {/* Active rows: queued + running */}
      <ul className="space-y-1 text-sm">
        {[...queued, ...running].map((row) => (
          <QueueRowLine
            key={row.sequence}
            row={row}
            disabled={discardMutation.isPending || applyMutation.isPending}
            pendingDiscardSeq={pendingDiscardSeq}
            onDiscard={() => {
              setPendingDiscardSeq(row.sequence);
              discardMutation.mutate(row.sequence, {
                onSettled: () => setPendingDiscardSeq(null),
              });
            }}
          />
        ))}
      </ul>

      {/* Actions */}
      <div className="flex gap-2">
        <button
          type="button"
          className="rounded bg-blue-700 px-3 py-1.5 text-sm text-white hover:bg-blue-600 disabled:bg-gray-700 disabled:text-gray-400"
          disabled={applyDisabled}
          onClick={() => applyMutation.mutate()}
        >
          {applyMutation.isPending
            ? 'Applying…'
            : queued.length > 0
              ? `Apply ${queued.length} change${queued.length === 1 ? '' : 's'}`
              : 'Apply'}
        </button>
        <button
          type="button"
          className="rounded border border-gray-600 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-800 disabled:text-gray-500"
          disabled={
            queued.length === 0 || discardMutation.isPending || anyRunning
          }
          onClick={() => discardMutation.mutate(undefined)}
        >
          Discard all queued
        </button>
      </div>

      {/* Terminal history (collapsed to a short tail) */}
      {terminal.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-gray-400">
            Recent history ({terminal.length})
          </summary>
          <ul className="mt-2 space-y-1">
            {terminal.slice(0, 10).map((row) => (
              <li
                key={row.sequence}
                className="flex items-baseline gap-2 text-gray-500"
              >
                <StatusTag status={row.status} />
                <span className="truncate">
                  #{row.sequence} {renderInstruction(row.instruction_type, row.payload)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function QueueRowLine({
  row,
  disabled,
  pendingDiscardSeq,
  onDiscard,
}: {
  row: QueueRow;
  disabled: boolean;
  pendingDiscardSeq: number | null;
  onDiscard: () => void;
}) {
  const thisPending = pendingDiscardSeq === row.sequence;
  return (
    <li className="flex items-baseline gap-2">
      <StatusTag status={row.status} />
      <span
        className="flex-1 truncate text-gray-200"
        title={renderInstruction(row.instruction_type, row.payload)}
      >
        #{row.sequence} {renderInstruction(row.instruction_type, row.payload)}
      </span>
      {row.status === 'queued' && (
        <button
          type="button"
          className="shrink-0 text-xs text-gray-400 hover:text-gray-200 disabled:text-gray-600"
          disabled={disabled}
          onClick={onDiscard}
        >
          {thisPending ? 'Discarding…' : 'Discard'}
        </button>
      )}
    </li>
  );
}

function StatusTag({ status }: { status: QueueRow['status'] }) {
  const color: Record<QueueRow['status'], string> = {
    queued: 'bg-gray-700 text-gray-200',
    running: 'bg-amber-700/60 text-amber-100 animate-pulse',
    applied: 'bg-emerald-800/60 text-emerald-200',
    discarded: 'bg-gray-800 text-gray-500',
    failed: 'bg-red-800/60 text-red-200',
  };
  return (
    <span
      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${color[status]}`}
    >
      {status}
    </span>
  );
}
