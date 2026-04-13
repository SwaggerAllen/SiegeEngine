import { useState } from 'react';
import { describeApiError } from '../lib/describeApiError';
import { XmlDocument } from './xml';
import type { XmlRendererMap } from './xml';

// ── Shared type shapes ─────────────────────────────────────────────

/**
 * The data shape this panel walks its state machine off of.
 * Every bootstrap-doc endpoint (expansion, requirements, sysarch,
 * subreqs, manifest) returns the same five pieces — the panel
 * takes a pre-extracted snapshot so callers can supply it from
 * whatever Zod schema their endpoint happens to use.
 */
export interface BootstrapPanelNode {
  id: string;
  name: string;
  content: string;
  updated_at: string;
}

export interface BootstrapPanelDraft {
  id: string;
  content: string;
  created_at: string;
}

export interface BootstrapPanelTelemetry {
  prompt_tokens: number;
  completion_tokens: number;
  model: string;
  created_at: string;
}

export type BootstrapGenerationStatus = 'idle' | 'running' | 'failed';

export interface BootstrapPanelData {
  node: BootstrapPanelNode;
  pending_draft: BootstrapPanelDraft | null;
  generation_status: BootstrapGenerationStatus;
  last_error: string | null;
  latest_telemetry: BootstrapPanelTelemetry | null;
}

/**
 * Human-readable labels that vary per-panel. Kept together in an
 * object so callers can define them in one place near their
 * endpoint wiring.
 */
export interface BootstrapPanelLabels {
  /** Shown in the "Generating…" spinner state. */
  generatingMessage: string;
  /** Heading above the pending-draft content, e.g. "Feature
   * Expansion — Draft". */
  draftHeading: string;
  /** Placeholder text for the feedback textarea. */
  feedbackPlaceholder: string;
  /** Small caption shown on the approved read-only view. */
  readOnlyExplanation: string;
  /** Error message prefix when the query itself fails. */
  loadErrorTitle: string;
  /** Caption under the loading state. */
  loadingMessage: string;
}

/**
 * Mutation callbacks the panel dispatches against. These are thin
 * — callers are expected to wire them to their own react-query
 * mutations in a couple of lines. The panel only calls these
 * functions; it doesn't care what hooks produced them.
 */
export interface BootstrapPanelCallbacks {
  /** Submit feedback and regenerate. */
  onFeedback: (feedback: string) => void;
  /** Approve the given pending draft id. */
  onApprove: (draftId: string) => void;
  /** Discard the given pending draft id (and, per the current
   * backend semantics, regenerate from scratch). */
  onDiscard: (draftId: string) => void;
  /** Kick off a fresh generation with no feedback (the
   * failed-state retry path). */
  onRetry: () => void;
  /** True while any of the mutations is in-flight. */
  isBusy: boolean;
}

interface Props {
  data: BootstrapPanelData | undefined;
  isLoading: boolean;
  error: unknown;
  labels: BootstrapPanelLabels;
  callbacks: BootstrapPanelCallbacks;
  /**
   * XML renderer map for the bootstrap doc's schema. See
   * ``components/xml/featureRenderers.tsx`` for the Phase 2
   * example — every phase ships its own map and passes it in.
   */
  contentRenderers: XmlRendererMap;
}

function TelemetryLine({ telemetry }: { telemetry: BootstrapPanelTelemetry | null }) {
  if (!telemetry) return null;
  return (
    <div className="text-xs text-gray-500 italic" data-testid="telemetry-line">
      Last gen: {telemetry.prompt_tokens.toLocaleString()} →{' '}
      {telemetry.completion_tokens.toLocaleString()} tokens · {telemetry.model}
    </div>
  );
}

/**
 * The four-state bootstrap-doc panel shell.
 *
 * Each of the v2 bootstrap docs (expansion, requirements, sysarch,
 * subreqs, manifest) goes through the same state machine —
 * loading → generating → pending-draft review → approved
 * read-only → failed-no-content. This component owns that state
 * machine. Callers hook up their own react-query data source and
 * mutation handlers, pass in a schema renderer map, and get the
 * full four-state experience for free.
 *
 * Callers can customize the human-readable strings via ``labels``
 * but the structural behavior is identical so users only have to
 * learn one draft-review UI across the whole cold-start chain.
 */
export function BootstrapDraftPanel({
  data,
  isLoading,
  error,
  labels,
  callbacks,
  contentRenderers,
}: Props) {
  const [feedback, setFeedback] = useState('');

  if (isLoading) {
    return <div className="p-6 text-gray-400 text-sm">{labels.loadingMessage}</div>;
  }
  if (error) {
    return (
      <div className="p-6 text-red-400 text-sm">
        {describeApiError(error, labels.loadErrorTitle)}
      </div>
    );
  }
  if (!data) return null;

  const { node, pending_draft, generation_status, last_error, latest_telemetry } = data;

  const submitFeedback = () => {
    const trimmed = feedback.trim();
    if (!trimmed) return;
    callbacks.onFeedback(trimmed);
    setFeedback('');
  };

  // State 1: generating, no pending draft yet.
  if (generation_status === 'running' && !pending_draft) {
    return (
      <div className="p-6 flex flex-col items-center justify-center gap-3 text-gray-300">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-600 border-t-blue-400" />
        <div className="text-sm">{labels.generatingMessage}</div>
      </div>
    );
  }

  // State 2: pending draft present (review mode).
  if (pending_draft) {
    return (
      <div className="p-6 space-y-4 max-w-4xl mx-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">{labels.draftHeading}</h2>
          {generation_status === 'running' && (
            <span className="text-xs text-gray-400">regenerating…</span>
          )}
        </div>
        <XmlDocument content={pending_draft.content} renderers={contentRenderers} />
        <div className="space-y-2">
          <label className="block text-xs text-gray-400">
            Feedback for regeneration (optional)
          </label>
          <textarea
            className="w-full h-24 bg-gray-900 border border-gray-700 rounded p-2 text-sm"
            placeholder={labels.feedbackPlaceholder}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            disabled={callbacks.isBusy}
          />
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            type="button"
            onClick={submitFeedback}
            disabled={callbacks.isBusy || !feedback.trim()}
            className="px-4 py-2 text-sm rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-40"
          >
            Regenerate
          </button>
          <button
            type="button"
            onClick={() => callbacks.onApprove(pending_draft.id)}
            disabled={callbacks.isBusy}
            className="px-4 py-2 text-sm rounded bg-green-700 hover:bg-green-600 disabled:opacity-40"
          >
            Approve
          </button>
          <button
            type="button"
            onClick={() => callbacks.onDiscard(pending_draft.id)}
            disabled={callbacks.isBusy}
            className="px-4 py-2 text-sm rounded bg-red-900 hover:bg-red-800 disabled:opacity-40"
            title="Discard this draft and generate a new one from scratch"
          >
            Reject &amp; Regenerate
          </button>
        </div>
        <TelemetryLine telemetry={latest_telemetry} />
      </div>
    );
  }

  // State 4: failed, no content, no pending draft.
  if (generation_status === 'failed' && !node.content) {
    return (
      <div className="p-6 max-w-4xl mx-auto space-y-4">
        <div className="p-4 border border-red-800 bg-red-950/40 rounded text-sm text-red-300">
          <div className="font-semibold mb-1">Generation failed</div>
          {last_error && <div className="text-red-400/80">{last_error}</div>}
        </div>
        <button
          type="button"
          onClick={callbacks.onRetry}
          disabled={callbacks.isBusy}
          className="px-4 py-2 text-sm rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40"
        >
          Retry
        </button>
        <TelemetryLine telemetry={latest_telemetry} />
      </div>
    );
  }

  // State 3: approved content, read-only.
  if (node.content) {
    return (
      <div className="p-6 space-y-4 max-w-4xl mx-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">{node.name}</h2>
          <span className="text-xs text-gray-500 uppercase tracking-wide">
            Approved · read-only
          </span>
        </div>
        <XmlDocument content={node.content} renderers={contentRenderers} />
        <div className="text-xs text-gray-500 italic">{labels.readOnlyExplanation}</div>
        <TelemetryLine telemetry={latest_telemetry} />
      </div>
    );
  }

  // State 3b: node exists but has no content and no pending draft —
  // pre-bootstrap empty state (shouldn't normally be reached on the
  // happy path).
  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{node.name}</h2>
      </div>
      <div className="text-sm text-gray-400 italic">No approved content yet.</div>
    </div>
  );
}
