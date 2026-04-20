import { useMemo, useState } from 'react';
import { useFeedbackHistory } from '../hooks/queries/useFeedbackHistory';
import { describeApiError } from '../lib/describeApiError';
import { CopyButton } from './CopyButton';

/**
 * Phase-11 followup B9 — aggregate feedback history panel.
 *
 * Collapsible section showing every prose feedback entry ever
 * left on this node: user regeneration feedback (from the job
 * payloads) + AI review text (from draft rows). Top-level
 * "Copy all" button dumps the combined history as plain text
 * so the user can hand it to the LLM (or to a human reviewer)
 * to pattern-match what prompts are missing.
 *
 * Mounts inside BootstrapDraftPanel + FanInPanel.
 */
export function FeedbackHistory({
  projectId,
  nodeId,
}: {
  projectId: string;
  nodeId: string | null | undefined;
}) {
  const [open, setOpen] = useState(false);
  const { data, error, isLoading } = useFeedbackHistory(projectId, nodeId);

  const combined = useMemo(() => {
    if (!data) return '';
    return data.entries
      .map(
        (e) =>
          `## ${e.source === 'user' ? 'User feedback' : 'AI review'} — ${e.created_at}\n\n${e.text}`,
      )
      .join('\n\n---\n\n');
  }, [data]);

  if (!nodeId) return null;

  // Nothing yet to show. Hide the section entirely so we don't
  // add chrome for an empty list.
  if (!isLoading && !error && data && data.entries.length === 0) {
    return null;
  }

  return (
    <details
      className="mt-4 border border-gray-800 rounded bg-gray-950"
      open={open}
      onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="cursor-pointer px-3 py-2 text-sm text-gray-300 hover:text-gray-100 select-none">
        Feedback history
        {data ? ` (${data.entries.length})` : ''}
      </summary>
      <div className="px-3 pb-3 space-y-3">
        {isLoading && (
          <p className="text-xs text-gray-500">Loading feedback history…</p>
        )}
        {error && (
          <p className="text-xs text-red-400">
            {describeApiError(error, 'Failed to load feedback history')}
          </p>
        )}
        {data && data.entries.length > 0 && (
          <>
            <div className="flex justify-end">
              <CopyButton
                content={combined}
                label="Copy all"
                title="Copy every entry as plain text"
              />
            </div>
            <ul className="space-y-3">
              {data.entries.map((e, idx) => (
                <li
                  key={`${e.created_at}-${idx}`}
                  className="rounded border border-gray-800 bg-gray-900 p-2"
                >
                  <div className="flex items-baseline justify-between text-xs text-gray-500 mb-1">
                    <span
                      className={
                        e.source === 'user'
                          ? 'text-blue-300'
                          : 'text-purple-300'
                      }
                    >
                      {e.source === 'user' ? 'User feedback' : 'AI review'}
                    </span>
                    <span>{e.created_at}</span>
                  </div>
                  <p className="whitespace-pre-wrap text-sm text-gray-200">
                    {e.text}
                  </p>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </details>
  );
}
