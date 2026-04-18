import { useState } from 'react';
import { useFanIn } from '../hooks/queries/useFanInQueries';
import {
  useFanInCancelMutation,
  useFanInRegenerateMutation,
  useFanInResetMutation,
  useFanInReviewRetryMutation,
} from '../hooks/mutations/useFanInMutations';
import { describeApiError } from '../lib/describeApiError';
import { CollapsibleMarkdown } from './editor/CollapsibleMarkdown';
import { XmlDocument, faninRenderers } from './xml';

interface Props {
  projectId: string;
  compId: string;
  ownerName: string;
}

/**
 * Read-only inspection panel for a Phase 7 fan-in node.
 *
 * Fan-in has no draft lifecycle — content is written directly
 * via ``FanInContentUpdated``, not through the draft + approve
 * pipeline. So this panel is a slim three-state machine:
 *
 *   1. Loading / error
 *   2. Empty shell (no content yet; hasn't been regenerated once)
 *   3. Content present — render the ``<fanin>`` XML + controls
 *
 * The only user actions are Regenerate (manually enqueue a
 * fresh synthesis) and Cancel (stop one in flight). Normally
 * regen is driven by impl approvals via the backend
 * ``on_impl_approved`` hook; this panel exists for debugging
 * and for the user to re-run with updated prompt state.
 */
export function FanInPanel({ projectId, compId, ownerName }: Props) {
  const { data, error, isLoading } = useFanIn(projectId, compId);
  const regenerate = useFanInRegenerateMutation(projectId, compId);
  const cancel = useFanInCancelMutation(projectId, compId);
  const reset = useFanInResetMutation(projectId, compId);
  const retryReview = useFanInReviewRetryMutation(projectId, compId);
  const [confirmingReset, setConfirmingReset] = useState(false);

  if (isLoading) {
    return (
      <div className="p-6 text-sm text-gray-400">
        Loading {ownerName} fan-in synthesis…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 max-w-2xl">
        <h2 className="text-lg font-semibold text-red-400 mb-2">
          Failed to load fan-in
        </h2>
        <p className="text-sm text-gray-400">
          {describeApiError(error, 'Unknown error')}
        </p>
        <p className="text-xs text-gray-500 mt-2">
          Fan-in synthesis nodes only exist for fanned-out domain
          components. Presentational or un-fanned-out components
          don't have them.
        </p>
      </div>
    );
  }

  if (!data) return null;

  const isRunning = data.generation_status === 'running';
  const isBusy =
    regenerate.isPending ||
    cancel.isPending ||
    reset.isPending ||
    retryReview.isPending;
  const hasContent = !!data.node.content.trim();

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <header className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-white">{ownerName} Fan-in</h2>
          <p className="text-xs text-gray-500 mt-1 max-w-2xl">
            Bottom-up synthesis of what this component, as built,
            exposes and does at the component level. Driven by the
            subs' approved implementations. Presentational
            counterparts read this alongside the top-down
            comparch to surface drift.
          </p>
        </div>
        <div className="shrink-0 flex items-center gap-2">
          {isRunning ? (
            <button
              type="button"
              onClick={() => cancel.mutate()}
              disabled={isBusy}
              className="px-3 py-1.5 text-sm rounded border border-red-700/50 text-red-300 hover:bg-red-950 disabled:opacity-50"
            >
              Stop
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={() => regenerate.mutate()}
                disabled={isBusy}
                className="px-3 py-1.5 text-sm rounded border border-purple-700/50 text-purple-200 hover:bg-purple-950 disabled:opacity-50"
                title="Re-run the fan-in synthesis against the current impls."
              >
                {regenerate.isPending ? 'Starting…' : 'Regenerate'}
              </button>
              {confirmingReset ? (
                <button
                  type="button"
                  onClick={() => {
                    reset.mutate();
                    setConfirmingReset(false);
                  }}
                  onBlur={() => setConfirmingReset(false)}
                  disabled={isBusy}
                  autoFocus
                  className="px-3 py-1.5 text-sm rounded border border-red-700 bg-red-950 text-red-200 hover:bg-red-900 disabled:opacity-50"
                  title="Clear the fan-in content and re-enqueue generation."
                >
                  Confirm reset
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmingReset(true)}
                  disabled={isBusy || !hasContent}
                  className="px-3 py-1.5 text-sm rounded border border-red-800/40 text-red-300 hover:bg-red-950 disabled:opacity-40"
                  title="Destructively clear content and regen. Two-click confirm."
                >
                  Reset
                </button>
              )}
            </>
          )}
        </div>
      </header>

      <FanInStatusRow data={data} />

      {isRunning && (
        <div className="p-3 rounded border border-purple-800/50 bg-purple-950/30 text-sm text-purple-200">
          Fan-in synthesis is running. The panel polls every two
          seconds; new content will appear here when the job
          completes.
        </div>
      )}

      {data.last_error && (
        <div className="p-3 rounded border border-red-800/50 bg-red-950/30 text-sm text-red-200">
          <div className="font-semibold mb-1">Last generation failed</div>
          <pre className="whitespace-pre-wrap font-mono text-xs text-red-300">
            {data.last_error}
          </pre>
        </div>
      )}

      {hasContent ? (
        <section className="rounded border border-gray-800 bg-gray-900/50 p-4 space-y-3">
          <XmlDocument content={data.node.content} renderers={faninRenderers} />
          <FanInReviewBlock
            reviewText={data.review_text}
            reviewStatus={data.review_status}
            reviewLastError={data.review_last_error}
            reviewCurrentAttempt={data.review_current_attempt}
            reviewMaxAttempts={data.review_max_attempts}
            onRetryReview={() => retryReview.mutate()}
            isBusy={isBusy}
          />
        </section>
      ) : (
        <section className="rounded border border-gray-800 bg-gray-900/30 p-6 text-center">
          <p className="text-sm text-gray-400 mb-2">
            No fan-in content yet.
          </p>
          <p className="text-xs text-gray-500">
            Fan-in content is generated automatically after the
            first descendant implementation is approved. You can
            also click Regenerate above to kick one off manually.
          </p>
        </section>
      )}
    </div>
  );
}

function FanInReviewBlock({
  reviewText,
  reviewStatus,
  reviewLastError,
  reviewCurrentAttempt,
  reviewMaxAttempts,
  onRetryReview,
  isBusy,
}: {
  reviewText: string;
  reviewStatus: 'idle' | 'running' | 'failed';
  reviewLastError: string | null;
  reviewCurrentAttempt: number | null;
  reviewMaxAttempts: number | null;
  onRetryReview: () => void;
  isBusy: boolean;
}) {
  if (reviewStatus === 'running') {
    const attemptLabel =
      reviewCurrentAttempt && reviewMaxAttempts
        ? ` · attempt ${reviewCurrentAttempt} / ${reviewMaxAttempts}`
        : '';
    return (
      <div
        className="flex items-center gap-3 text-xs text-gray-400 border-t border-gray-800 pt-3"
        data-testid="review-running"
      >
        <div className="h-3 w-3 animate-spin rounded-full border-2 border-gray-600 border-t-blue-400" />
        <span>Reviewing…{attemptLabel}</span>
      </div>
    );
  }
  if (reviewStatus === 'failed') {
    return (
      <div
        className="border-t border-gray-800 pt-3 space-y-2"
        data-testid="review-failed"
      >
        <div className="p-3 border border-red-800 bg-red-950/40 rounded text-xs text-red-300">
          <div className="font-semibold mb-1">AI review failed</div>
          {reviewLastError && (
            <div className="text-red-400/80 whitespace-pre-wrap">{reviewLastError}</div>
          )}
        </div>
        <button
          type="button"
          onClick={onRetryReview}
          disabled={isBusy}
          className="px-3 py-1 text-xs rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40"
          data-testid="review-retry-button"
        >
          Retry review
        </button>
      </div>
    );
  }
  if (reviewText.trim()) {
    return (
      <div
        className="border-t border-gray-800 pt-3"
        data-testid="review-text"
      >
        <CollapsibleMarkdown className="text-sm text-gray-300 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-gray-200 [&_h2]:mt-2 [&_h2]:mb-1">
          {`# AI Review\n\n${reviewText}`}
        </CollapsibleMarkdown>
      </div>
    );
  }
  return null;
}

function FanInStatusRow({
  data,
}: {
  data: {
    generation_status: string;
    latest_telemetry: {
      prompt_tokens: number;
      completion_tokens: number;
      model: string;
      created_at: string;
    } | null;
    current_attempt: number | null;
    max_attempts: number | null;
    node: { updated_at: string };
  };
}) {
  const t = data.latest_telemetry;
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-gray-400">
      <span>
        Status:{' '}
        <span
          className={
            data.generation_status === 'running'
              ? 'text-purple-300'
              : data.generation_status === 'failed'
                ? 'text-red-300'
                : 'text-gray-200'
          }
        >
          {data.generation_status}
        </span>
      </span>
      {data.current_attempt !== null && data.max_attempts !== null && (
        <span>
          Attempt {data.current_attempt} / {data.max_attempts}
        </span>
      )}
      {t && (
        <>
          <span>Model: {t.model}</span>
          <span>Tokens: {t.prompt_tokens} in / {t.completion_tokens} out</span>
        </>
      )}
      {data.node.updated_at && (
        <span>
          Updated: {new Date(data.node.updated_at).toLocaleString()}
        </span>
      )}
    </div>
  );
}
