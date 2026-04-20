import { useState } from 'react';
import type { InstructionRow } from '../../api/queue';
import {
  useApplyQueue,
  useDiscardAll,
  useDiscardOne,
  useProjectQueue,
  useRetryInstruction,
} from '../../hooks/queries/useProjectQueue';

interface Props {
  projectId: string;
}

/**
 * Phase 11 — pending-change queue panel.
 *
 * Renders queued / failed / recently-applied instructions plus
 * toolbar actions (Apply, Discard all). Every UI edit affordance
 * in the workspace drops an instruction here; the user reviews the
 * batch and hits Apply to fire a single `v2.apply_instructions`
 * job that runs them in sequence.
 */
export function QueuePanelView({ projectId }: Props) {
  const { data, isLoading, error } = useProjectQueue(projectId);
  const applyMutation = useApplyQueue(projectId);
  const discardAllMutation = useDiscardAll(projectId);
  const discardOne = useDiscardOne(projectId);
  const retryInstruction = useRetryInstruction(projectId);
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  if (isLoading) {
    return <div className="p-6 text-sm text-gray-400">Loading queue…</div>;
  }
  if (error || !data) {
    return (
      <div className="p-6 text-sm text-red-400">
        Failed to load the pending-change queue.
      </div>
    );
  }

  const queuedCount = data.queued.length;
  const applyDisabled =
    queuedCount === 0 || data.apply_in_flight || applyMutation.isPending;

  return (
    <div className="h-full w-full flex flex-col overflow-hidden">
      <div className="flex items-center gap-3 border-b border-gray-800 px-4 py-2 text-sm">
        <span className="text-gray-300">
          <span className="font-medium text-gray-100">{queuedCount}</span>{' '}
          pending
          {data.failed.length > 0 && (
            <span className="ml-3 text-red-400">
              · {data.failed.length} failed
            </span>
          )}
          {data.apply_in_flight && (
            <span className="ml-3 text-amber-400">· applying…</span>
          )}
        </span>
        <div className="flex-1" />
        <button
          type="button"
          disabled={queuedCount === 0}
          onClick={() => setConfirmDiscard(true)}
          className="px-3 py-1 rounded text-xs bg-gray-800 hover:bg-gray-700 text-gray-200 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Discard all
        </button>
        <button
          type="button"
          disabled={applyDisabled}
          onClick={() => applyMutation.mutate()}
          className="px-3 py-1 rounded text-xs bg-emerald-700 hover:bg-emerald-600 text-white font-medium disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {applyMutation.isPending || data.apply_in_flight
            ? 'Applying…'
            : 'Apply changes'}
        </button>
      </div>

      <div className="flex-1 overflow-auto px-4 py-3 space-y-6">
        {data.failed.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-red-400 mb-2">
              Failed
            </h3>
            <ul className="space-y-2">
              {data.failed.map((row) => (
                <FailedRow
                  key={row.id}
                  row={row}
                  onRetry={() => retryInstruction.mutate(row.id)}
                  onDiscard={() => discardOne.mutate(row.id)}
                />
              ))}
            </ul>
          </section>
        )}

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">
            Queued ({queuedCount})
          </h3>
          {queuedCount === 0 ? (
            <p className="text-sm text-gray-500 italic">
              No pending changes. Edit affordances elsewhere in the
              workspace enqueue here.
            </p>
          ) : (
            <ul className="space-y-1">
              {data.queued.map((row) => (
                <QueuedRow
                  key={row.id}
                  row={row}
                  onDiscard={() => discardOne.mutate(row.id)}
                />
              ))}
            </ul>
          )}
        </section>

        {data.recent_applied.length > 0 && (
          <details className="text-sm text-gray-400">
            <summary className="cursor-pointer uppercase text-xs tracking-wider font-semibold mb-2">
              Recently applied ({data.recent_applied.length})
            </summary>
            <ul className="mt-2 space-y-1">
              {data.recent_applied.map((row) => (
                <li key={row.id} className="text-xs text-gray-500">
                  <span className="font-mono text-[10px] mr-2 text-gray-600">
                    #{row.sequence}
                  </span>
                  {row.rendered}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      {confirmDiscard && (
        <ConfirmDiscardDialog
          count={queuedCount}
          onCancel={() => setConfirmDiscard(false)}
          onConfirm={() => {
            setConfirmDiscard(false);
            discardAllMutation.mutate();
          }}
        />
      )}
    </div>
  );
}

function QueuedRow({
  row,
  onDiscard,
}: {
  row: InstructionRow;
  onDiscard: () => void;
}) {
  return (
    <li className="flex items-start gap-2 py-1 px-2 rounded bg-gray-900/40 border border-gray-800 text-sm text-gray-200">
      <span className="font-mono text-[10px] text-gray-500 mt-0.5 shrink-0">
        #{row.sequence}
      </span>
      <span className="flex-1 min-w-0 whitespace-pre-wrap break-words">
        {row.rendered}
      </span>
      <button
        type="button"
        aria-label="Discard"
        onClick={onDiscard}
        className="shrink-0 text-gray-500 hover:text-red-400 px-1"
      >
        ×
      </button>
    </li>
  );
}

function FailedRow({
  row,
  onRetry,
  onDiscard,
}: {
  row: InstructionRow;
  onRetry: () => void;
  onDiscard: () => void;
}) {
  return (
    <li className="p-2 rounded border border-red-900/60 bg-red-950/30 text-sm text-gray-200">
      <div className="flex items-start gap-2">
        <span className="font-mono text-[10px] text-gray-500 mt-0.5">
          #{row.sequence}
        </span>
        <span className="flex-1 whitespace-pre-wrap break-words">
          {row.rendered}
        </span>
      </div>
      {row.error && (
        <pre className="mt-2 text-xs text-red-300 whitespace-pre-wrap break-words font-mono">
          {row.error}
        </pre>
      )}
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          onClick={onRetry}
          className="px-2 py-0.5 rounded text-xs bg-gray-800 hover:bg-gray-700 text-gray-200"
        >
          Retry
        </button>
        <button
          type="button"
          onClick={onDiscard}
          className="px-2 py-0.5 rounded text-xs bg-gray-800 hover:bg-gray-700 text-gray-400"
        >
          Discard
        </button>
      </div>
    </li>
  );
}

function ConfirmDiscardDialog({
  count,
  onCancel,
  onConfirm,
}: {
  count: number;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      className="absolute inset-0 bg-black/60 flex items-center justify-center"
    >
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 max-w-sm text-sm text-gray-200">
        <p>Discard all {count} pending changes? This cannot be undone.</p>
        <div className="mt-4 flex gap-2 justify-end">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1 rounded bg-gray-800 hover:bg-gray-700"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-3 py-1 rounded bg-red-700 hover:bg-red-600 text-white"
          >
            Discard all
          </button>
        </div>
      </div>
    </div>
  );
}
