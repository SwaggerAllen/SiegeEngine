import { useEffect, useState } from 'react';
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
  /**
   * ISO-8601 UTC timestamp (naive) of when the currently-running
   * generation job was enqueued. ``null`` when no generation is
   * running. Drives the regeneration duration clock + PST start-
   * time label the panel renders alongside the Stop button.
   */
  generation_started_at: string | null;
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
  /** Submit (possibly-empty) feedback and regenerate. The handler
   * always sees the current pending draft as ``prior_pending`` so
   * the LLM can iterate on what it produced last time, rather than
   * regenerating from scratch. Called by the single
   * "Reject & Regenerate" button in the pending-draft state. */
  onFeedback: (feedback: string) => void;
  /** Approve the given pending draft id. */
  onApprove: (draftId: string) => void;
  /** Kick off a fresh generation with no feedback (the
   * failed-state retry path). */
  onRetry: () => void;
  /** Stop the currently-running generation. The backend cancels
   * the queued/running job and the status query flips back to
   * ``idle``, dropping the user back into the feedback / accept /
   * reject state over any remaining pending draft. */
  onCancel: () => void;
  /**
   * Destructively reset an **approved** bootstrap node — nuke all
   * downstream state it minted and re-enqueue a fresh generation.
   * Only wired by panels that have a corresponding backend reset
   * route (currently just sysarch). When absent, the approved
   * read-only state shows no reset affordance — matching the
   * historical behavior for tiers that can't be reset yet.
   */
  onReset?: () => void;
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
 * Format a duration in seconds as a short human-readable string:
 * ``45s``, ``2m 05s``, ``1h 03m``. Used by the regeneration
 * duration clock so the ticking counter stays compact next to
 * the Stop button.
 */
function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rs = s % 60;
  if (m < 60) return `${m}m ${rs.toString().padStart(2, '0')}s`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return `${h}h ${rm.toString().padStart(2, '0')}m`;
}

/**
 * Duration clock + PST start-time label rendered while a
 * generation is running. Ticks once a second via a
 * ``setInterval`` local to the component so the rest of the
 * panel doesn't re-render on every tick.
 *
 * ``startedAtIso`` is the backend-reported job created_at (naive
 * UTC ISO-8601). We parse it as UTC by appending ``Z`` if the
 * server didn't. If it's absent (e.g. in the regeneration
 * optimistic path before the first poll lands), we fall back to
 * an empty label so the UI stays stable.
 */
function GenerationClock({
  startedAtIso,
  variant = 'inline',
}: {
  startedAtIso: string | null;
  variant?: 'inline' | 'block';
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!startedAtIso) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [startedAtIso]);

  if (!startedAtIso) return null;

  // Backend hands us a naive UTC ISO string (``datetime.utcnow``);
  // append ``Z`` if it's missing a timezone so Date parses it as
  // UTC rather than local.
  const iso = /[Zz]|[+-]\d\d:?\d\d$/.test(startedAtIso)
    ? startedAtIso
    : `${startedAtIso}Z`;
  const startMs = Date.parse(iso);
  if (Number.isNaN(startMs)) return null;

  const elapsed = (now - startMs) / 1000;
  const duration = formatDuration(elapsed);
  // PST per the user's request. ``America/Los_Angeles`` follows
  // DST; label it "PT" to cover both PST/PDT without lying.
  const startedLabel = new Date(startMs).toLocaleTimeString('en-US', {
    timeZone: 'America/Los_Angeles',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });

  if (variant === 'block') {
    return (
      <div className="text-xs text-gray-400 text-center" data-testid="generation-clock">
        <div>Elapsed: {duration}</div>
        <div className="text-gray-500">started {startedLabel} PT</div>
      </div>
    );
  }
  return (
    <span className="text-xs text-gray-400" data-testid="generation-clock">
      {duration} · started {startedLabel} PT
    </span>
  );
}

/**
 * Two-click confirm for the destructive reset action on the
 * approved-state panel. First click flips the button into "Are
 * you sure?" mode; a second click within that mode calls through
 * to ``onReset``. Clicking anywhere else on the control row
 * cancels the pending confirm.
 *
 * Two-click confirm rather than a full modal because the page is
 * already busy and a modal would add more chrome than the action
 * warrants. The visual distinction (red button text → "Confirm
 * reset — nukes downstream state" in red background) is enough
 * to make the destructive nature obvious.
 */
function ResetApprovedStateControl({
  onReset,
  isBusy,
}: {
  onReset: () => void;
  isBusy: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  return (
    <div className="pt-4 border-t border-gray-800 flex items-center gap-3 flex-wrap">
      {confirming ? (
        <>
          <button
            type="button"
            onClick={() => {
              onReset();
              setConfirming(false);
            }}
            disabled={isBusy}
            className="px-4 py-2 text-sm rounded bg-red-700 hover:bg-red-600 disabled:opacity-40"
          >
            Confirm reset — this will delete all downstream state
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            disabled={isBusy}
            className="px-4 py-2 text-sm rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-40"
          >
            Cancel
          </button>
        </>
      ) : (
        <>
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={isBusy}
            className="px-4 py-2 text-sm rounded border border-red-900 text-red-300 hover:bg-red-950 disabled:opacity-40"
            title="Destructively reset this approved doc and all state minted from its approval"
          >
            Reset &amp; Regenerate
          </button>
          <span className="text-xs text-gray-500">
            Deletes every downstream component, policy, subreqs, and
            pending draft this approval minted, then regenerates
            against the current prompt. Upstream state (features,
            top-level responsibilities) is untouched.
          </span>
        </>
      )}
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

  const {
    node,
    pending_draft,
    generation_status,
    last_error,
    latest_telemetry,
    generation_started_at,
  } = data;

  const submitFeedback = () => {
    // Passes through whatever is in the textarea, trimmed — empty
    // string OK. The feedback endpoint always uses the current
    // pending draft as ``prior_pending``, so an empty feedback
    // still gives the LLM a do-over with its own prior attempt
    // visible. This merges the former split between "Regenerate
    // with feedback" (required text) and "Reject & Regenerate"
    // (silently discard and start over) into one affordance.
    const trimmed = feedback.trim();
    callbacks.onFeedback(trimmed);
    setFeedback('');
  };

  // State 1: generating, no pending draft yet.
  if (generation_status === 'running' && !pending_draft) {
    return (
      <div className="p-6 flex flex-col items-center justify-center gap-3 text-gray-300">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-600 border-t-blue-400" />
        <div className="text-sm">{labels.generatingMessage}</div>
        <GenerationClock startedAtIso={generation_started_at} variant="block" />
        <button
          type="button"
          onClick={callbacks.onCancel}
          disabled={callbacks.isBusy}
          className="px-4 py-2 text-sm rounded bg-red-900 hover:bg-red-800 disabled:opacity-40"
          title="Stop this generation and return to the previous state"
          data-testid="generation-stop-button"
        >
          Stop
        </button>
      </div>
    );
  }

  // State 2: pending draft present (review mode).
  if (pending_draft) {
    const isRegenerating = generation_status === 'running';
    return (
      <div className="max-w-4xl mx-auto">
        <div className="p-6 pb-0 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">{labels.draftHeading}</h2>
            {isRegenerating && (
              <div className="flex items-center gap-3">
                <span className="text-xs text-gray-400">regenerating…</span>
                <GenerationClock startedAtIso={generation_started_at} />
                <button
                  type="button"
                  onClick={callbacks.onCancel}
                  disabled={callbacks.isBusy}
                  className="px-3 py-1 text-xs rounded bg-red-900 hover:bg-red-800 disabled:opacity-40"
                  title="Stop this regeneration and return to the previous draft"
                  data-testid="generation-stop-button"
                >
                  Stop
                </button>
              </div>
            )}
          </div>
          <XmlDocument content={pending_draft.content} renderers={contentRenderers} />
          <TelemetryLine telemetry={latest_telemetry} />
        </div>
        <div className="sticky bottom-0 bg-gray-950 border-t border-gray-800 p-4 space-y-3">
          <label className="block text-xs text-gray-400">
            Feedback for regeneration (optional)
          </label>
          <textarea
            className="w-full h-20 bg-gray-900 border border-gray-700 rounded p-2 text-sm"
            placeholder={labels.feedbackPlaceholder}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            disabled={callbacks.isBusy || isRegenerating}
          />
          <div className="flex gap-2 flex-wrap">
            <button
              type="button"
              onClick={() => callbacks.onApprove(pending_draft.id)}
              disabled={callbacks.isBusy || isRegenerating}
              className="px-4 py-2 text-sm rounded bg-green-700 hover:bg-green-600 disabled:opacity-40"
            >
              Approve
            </button>
            <button
              type="button"
              onClick={submitFeedback}
              disabled={callbacks.isBusy || isRegenerating}
              className="px-4 py-2 text-sm rounded bg-red-900 hover:bg-red-800 disabled:opacity-40"
              title={
                feedback.trim()
                  ? 'Regenerate this draft with the feedback above; the LLM sees the current draft as its starting point'
                  : 'Regenerate this draft (LLM sees the current draft as starting point; add feedback above for targeted guidance)'
              }
            >
              Reject &amp; Regenerate
            </button>
          </div>
        </div>
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
        {callbacks.onReset && (
          <ResetApprovedStateControl
            onReset={callbacks.onReset}
            isBusy={callbacks.isBusy}
          />
        )}
      </div>
    );
  }

  // State 3b: node exists but has no content and no pending draft —
  // pre-bootstrap empty state. Also the state the user lands in
  // after stopping an initial generation that had no prior draft,
  // so we include a "Generate" button to kick a fresh run.
  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{node.name}</h2>
      </div>
      <div className="text-sm text-gray-400 italic">No approved content yet.</div>
      <button
        type="button"
        onClick={callbacks.onRetry}
        disabled={callbacks.isBusy}
        className="px-4 py-2 text-sm rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40"
      >
        Generate
      </button>
    </div>
  );
}
