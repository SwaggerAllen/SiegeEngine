import { useCallback, useMemo, useState } from 'react';
import { describeApiError } from '../lib/describeApiError';
import type { DraftDocKind } from '../lib/extractDraftSections';
import { DocPageMeta, type DocPageLastGenerationJob } from './DocPageMeta';
import { DocumentReviewTabs, type ExtraTab } from './DocumentReviewTabs';
import { DraftDiffView } from './DraftDiffView';
import { FeedbackHistory } from './FeedbackHistory';
import { GenerationClock } from './GenerationClock';
import { StructuredDraftDiffView } from './StructuredDraftDiffView';
import { XmlDocument } from './xml';
import type { XmlRendererMap } from './xml';

function CopyButton({
  content,
  label = 'Copy',
  title = 'Copy raw content to clipboard',
}: {
  content: string;
  label?: string;
  title?: string;
}) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [content]);
  return (
    <button
      type="button"
      onClick={handleCopy}
      className="px-3 py-1 text-xs rounded border border-gray-700 text-gray-400 hover:bg-gray-800 hover:text-gray-200"
      title={title}
    >
      {copied ? 'Copied' : label}
    </button>
  );
}

// ── Shared type shapes ─────────────────────────────────────────────

/**
 * The data shape this panel walks its state machine off of.
 * Every bootstrap-doc endpoint (expansion, requirements, sysarch,
 * manifest) returns the same five pieces — the panel
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
  /**
   * Phase 13 — generator's self-report of what this draft
   * changed / contains. Null on pre-Phase-13 drafts and on
   * drafts whose generator skipped the tag. Optional on the
   * interface so older tests + mocks that predate the field
   * don't have to re-mint the whole draft shape.
   */
  change_summary?: string | null;
}

export interface BootstrapPanelTelemetry {
  prompt_tokens: number;
  completion_tokens: number;
  model: string;
  created_at: string;
}

export type BootstrapGenerationStatus = 'idle' | 'running' | 'failed';

export interface BootstrapPanelIntermediate {
  /** Human-readable label for the dropdown, e.g. ``"After pass 1"``. */
  label: string;
  /** Draft body — fed to the diff view as the "before" side when selected. */
  content: string;
  /** 1-indexed pass within the current regen run. */
  auto_revision_pass: number;
  /** Phase 13 — per-pass change summary (may be null). */
  change_summary?: string | null;
}

export type BootstrapLastGenerationJob = DocPageLastGenerationJob;

export interface BootstrapPanelData {
  node: BootstrapPanelNode;
  pending_draft: BootstrapPanelDraft | null;
  /**
   * Phase 12 — regen-time diff "before" content. The most recently
   * discarded draft's content for this target, or ``null`` when no
   * prior discarded draft exists (brand-new bootstrap, or the first
   * regen after approval — in which case the panel falls back to
   * the approved node content for the diff's "before" side).
   */
  previous_draft_content: string | null;
  /**
   * Phase 12 auto-revision — intermediate drafts produced by the
   * AI-driven revision loop scoped to the current regen run.
   * Rendered as additional entries in the diff view's "Compare
   * against" dropdown below the default ``Pre-regen`` baseline.
   * Empty when the loop isn't active or auto_revisions_requested=0.
   */
  auto_revision_intermediates: BootstrapPanelIntermediate[];
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
  /**
   * Current parse-validate attempt number (1-indexed) while a
   * generation is actively running, or ``null`` if the handler
   * hasn't entered the retry loop yet (queued, spinning up, or
   * not a bootstrap tier). Paired with ``max_attempts`` to show
   * "Attempt N / M" next to the generation timer.
   */
  current_attempt: number | null;
  /** Total parse-validate attempts allowed (initial + retries). */
  max_attempts: number | null;
  /**
   * Raw LLM output from the last failed attempt when the parse-
   * validate loop exhausted, so the failed-state UI can offer a
   * copy-to-clipboard affordance for debugging what the model
   * actually returned. ``null`` for other failure modes (CLI
   * crash before any attempt produced text) and for non-failed
   * states.
   */
  failed_raw_output: string | null;
  // Phase 8 — AI self-review fields. Surface independent of the
  // generation state machine above: review runs after draft
  // commit, lives on draft (or node, for fanin) as `review_text`,
  // and fails / retries independently.
  review_text: string;
  review_status: BootstrapGenerationStatus;
  review_last_error: string | null;
  /**
   * ISO-8601 UTC timestamp (naive) of when the currently-running
   * review job was enqueued. Drives the review-duration clock the
   * ReviewBlock renders alongside the "Reviewing…" spinner —
   * mirrors ``generation_started_at`` but for the review pass.
   */
  review_started_at: string | null;
  review_current_attempt: number | null;
  review_max_attempts: number | null;
  /**
   * Most recent generation job for this scope. Distinct from
   * ``generation_status`` — that field collapses cancelled and
   * completed into ``idle`` so the four-state UI doesn't treat
   * them as the failure state. This field preserves the raw
   * status so the doc-page header can show "last gen: cancelled
   * 12 min ago" when the user is staring at stale approved
   * content because the regen got cancelled.
   */
  last_generation_job: BootstrapLastGenerationJob | null;
  /**
   * ISO-8601 timestamp of the most recent ``NodeContentUpdated``
   * event for this node. Drives the "approved content last
   * landed" header line so the user can tell when the content
   * they're reading was actually written. ``null`` for nodes
   * that have never had a content-update event — typically
   * brand-new bootstraps that haven't been regenerated yet.
   */
  last_content_updated_at: string | null;
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
   * "Reject & Regenerate" button in the pending-draft state.
   *
   * ``autoRevisionsRequested`` (Phase 12) — when > 0, the backend
   * generate handler runs that many inline AI-review passes before
   * landing the final draft, each pass feeding its review findings
   * as feedback to the next pass. Only reqs reacts today; other
   * tiers accept and ignore.
   */
  onFeedback: (feedback: string, autoRevisionsRequested?: number) => void;
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
  /** Phase 8 — re-enqueue the AI self-review job when the prior
   * run failed. Absent on panels with no review wiring. */
  onRetryReview?: () => void;
  /** True while any of the mutations is in-flight. */
  isBusy: boolean;
}

interface Props {
  data: BootstrapPanelData | undefined;
  isLoading: boolean;
  error: unknown;
  labels: BootstrapPanelLabels;
  callbacks: BootstrapPanelCallbacks;
  contentRenderers: XmlRendererMap;
  /** Optional — when present, the B9 Feedback History panel is
   * mounted at the bottom of the panel for this project. */
  projectId?: string;
  /**
   * When set, the pending-draft Document tab renders a per-
   * section diff (one accordion per feature / responsibility /
   * component) instead of a single flat diff. Set on the
   * expansion, requirements, and sysarch panels; unset on
   * propagation tiers (comparch, impl, etc.) where the draft
   * isn't a list of uniform entries.
   */
  docKind?: DraftDocKind;
  /** Optional additional tabs inserted between Document and
   * Review. Callers typically derive these from the current
   * content (pending draft or approved node) so the user can
   * see a digested view alongside the raw XML. */
  extraTabs?: (args: {
    pendingContent: string | null;
    approvedContent: string | null;
  }) => ExtraTab[] | undefined;
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
function ResetApprovedStateControl(_props: {
  onReset: () => void;
  isBusy: boolean;
}) {
  // TODO Phase 3: replace with deep-link to the per-tier reset
  // skill in CC (e.g. /reset-<tier> <node_id>). Backend write
  // surface is going away; this is a placeholder so the layout
  // still shows the "destructive reset lives here" affordance.
  void _props;
  return (
    <div className="pt-4 border-t border-gray-800 flex items-center gap-3 flex-wrap">
      <button
        type="button"
        disabled
        className="px-4 py-2 text-sm rounded border border-red-900 text-red-300/60 cursor-not-allowed"
        title="Open the reset flow in Claude Code"
      >
        Open in Claude Code
      </button>
      <span className="text-xs text-gray-500">
        Destructive reset moved to Claude Code skills — invoke the per-tier
        reset skill there. The dashboard is read-only.
      </span>
    </div>
  );
}

/**
 * Document tab body for the pending-draft state. Wraps the raw
 * ``XmlDocument`` render in a Diff | Raw toggle so the user can
 * see what changed on a Reject & Regenerate before re-reading the
 * whole thing. Defaults to Diff when a prior version (discarded
 * draft or approved content) exists, to Raw otherwise.
 *
 * Lives inline rather than in its own file because it's a thin
 * view-mode switch — pure presentation over the same data the
 * panel already has.
 */
function PendingDraftDocumentTab({
  pendingContent,
  pendingSummary,
  previousDraftContent,
  approvedContent,
  intermediates,
  renderers,
  docKind,
}: {
  pendingContent: string;
  /**
   * Phase 13 — the pending draft's ``<change-summary>`` body (or
   * null). Rendered as the diff's header so the reviewer sees the
   * "why" before the "what" diff. Switches to the selected
   * intermediate's summary when the Compare-against dropdown
   * lands on one, so the header tracks the diff's right-hand side.
   */
  pendingSummary: string | null;
  previousDraftContent: string | null;
  approvedContent: string | null;
  intermediates: BootstrapPanelIntermediate[];
  renderers: XmlRendererMap;
  docKind?: DraftDocKind;
}) {
  // Build the ordered list of diff comparison options. Default
  // is "Pre-regen" (most recent user-visible discard, falling
  // back to approved content on first regen). Additional entries
  // are the auto-revision intermediates from the current run,
  // labeled server-side as ``After pass 1``, ``After pass 2``,
  // etc. If no pre-regen baseline exists (brand-new bootstrap)
  // there are no options and the diff is hidden entirely.
  const options = useMemo(() => {
    const preRegen =
      previousDraftContent !== null && previousDraftContent !== ''
        ? {
            label: 'Pre-regen',
            content: previousDraftContent,
            labelDetail: 'the previous draft',
          }
        : approvedContent && approvedContent.trim()
          ? {
              label: 'Approved content',
              content: approvedContent,
              labelDetail: 'the approved content (first regeneration)',
            }
          : null;
    const out: {
      label: string;
      content: string;
      labelDetail: string;
    }[] = [];
    if (preRegen) out.push(preRegen);
    for (const it of intermediates) {
      out.push({
        label: it.label,
        content: it.content,
        labelDetail: `auto-revision ${it.label.toLowerCase()}`,
      });
    }
    return out;
  }, [previousDraftContent, approvedContent, intermediates]);

  const hasDiff = options.length > 0;
  const [mode, setMode] = useState<'diff' | 'raw'>(hasDiff ? 'diff' : 'raw');
  const [selectedIdx, setSelectedIdx] = useState(0);
  // Clamp selection if the options list shrinks (e.g. intermediates
  // disappear on next regen cycle).
  const safeIdx = Math.min(selectedIdx, Math.max(options.length - 1, 0));
  const active = hasDiff ? options[safeIdx] : null;
  const diffLabel = active
    ? `Comparing pending against ${active.labelDetail}.`
    : '';

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        {hasDiff && (
          <div
            className="inline-flex text-xs rounded border border-gray-700 overflow-hidden"
            role="group"
            aria-label="Document view"
          >
            <button
              type="button"
              onClick={() => setMode('diff')}
              aria-pressed={mode === 'diff'}
              className={`px-3 py-1 ${
                mode === 'diff'
                  ? 'bg-gray-700 text-gray-100'
                  : 'bg-gray-900 text-gray-400 hover:bg-gray-800'
              }`}
            >
              Diff
            </button>
            <button
              type="button"
              onClick={() => setMode('raw')}
              aria-pressed={mode === 'raw'}
              className={`px-3 py-1 border-l border-gray-700 ${
                mode === 'raw'
                  ? 'bg-gray-700 text-gray-100'
                  : 'bg-gray-900 text-gray-400 hover:bg-gray-800'
              }`}
            >
              Raw
            </button>
          </div>
        )}
        {mode === 'diff' && options.length > 1 && (
          <label className="text-xs text-gray-400 flex items-center gap-2">
            Compare against:
            <select
              value={safeIdx}
              onChange={(e) => setSelectedIdx(Number(e.target.value))}
              className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200"
              aria-label="Diff comparison baseline"
            >
              {options.map((opt, i) => (
                <option key={opt.label} value={i}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {mode === 'diff' && active ? (
        docKind ? (
          <StructuredDraftDiffView
            before={active.content}
            after={pendingContent}
            kind={docKind}
            label={diffLabel}
            summaryText={pendingSummary}
          />
        ) : (
          <DraftDiffView
            before={active.content}
            after={pendingContent}
            label={diffLabel}
            summaryText={pendingSummary}
          />
        )
      ) : (
        <XmlDocument content={pendingContent} renderers={renderers} />
      )}
    </div>
  );
}

/**
 * The four-state bootstrap-doc panel shell.
 *
 * Each of the v2 bootstrap docs (expansion, requirements, sysarch,
 * manifest) goes through the same state machine —
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
  projectId,
  docKind,
  extraTabs,
}: Props) {
  // Phase 3 migration: feedback textarea + auto-revision counter
  // dropped along with their button. ``setReviewSelection`` is
  // kept as a no-op sink so the DocumentReviewTabs API contract
  // stays satisfied; the captured selection isn't consumed.
  const [, setReviewSelection] = useState('');

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
    previous_draft_content,
    auto_revision_intermediates,
    generation_status,
    last_error,
    latest_telemetry,
    generation_started_at,
    current_attempt,
    max_attempts,
    failed_raw_output,
    review_text,
    review_status,
    review_last_error,
    review_started_at,
    review_current_attempt,
    review_max_attempts,
    last_generation_job,
    last_content_updated_at,
  } = data;
  const docMeta = (
    <DocPageMeta
      lastGenerationJob={last_generation_job}
      lastContentUpdatedAt={last_content_updated_at}
    />
  );

  // Shared review state bundle — passed to DocumentReviewTabs
  // in both the pending-draft and approved-content branches.
  // Both branches always have reviewable content, so
  // ``allowGenerate`` is always true at those mount points.
  // The empty-state branches (loading, generating-with-no-draft,
  // failed-no-content, pre-bootstrap) render neither tabs nor
  // the review block.
  const reviewProps = {
    reviewText: review_text,
    reviewStatus: review_status,
    reviewLastError: review_last_error,
    reviewStartedAt: review_started_at,
    reviewCurrentAttempt: review_current_attempt,
    reviewMaxAttempts: review_max_attempts,
    onRetryReview: callbacks.onRetryReview,
    allowGenerate: true,
    isBusy: callbacks.isBusy,
  };

  // State 1: generating, no pending draft yet.
  if (generation_status === 'running' && !pending_draft) {
    return (
      <div className="p-6 max-w-4xl mx-auto space-y-4">
        <h2 className="text-lg font-semibold">{node.name}</h2>
        {docMeta}
        <div className="flex flex-col items-center justify-center gap-3 text-gray-300 pt-4">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-600 border-t-blue-400" />
          <div className="text-sm">{labels.generatingMessage}</div>
          <GenerationClock
            startedAtIso={generation_started_at}
            currentAttempt={current_attempt}
            maxAttempts={max_attempts}
            variant="block"
          />
          {/* TODO Phase 3: replace with deep-link to /cancel-<tier>
              in CC. Backend cancel route is going away. */}
          <button
            type="button"
            disabled
            className="px-4 py-2 text-sm rounded border border-red-900 text-red-300/60 cursor-not-allowed"
            title="Open in Claude Code to manage the generation"
            data-testid="generation-stop-button"
          >
            Open in Claude Code
          </button>
        </div>
      </div>
    );
  }

  // State 2: pending draft present (review mode).
  if (pending_draft) {
    const isRegenerating = generation_status === 'running';
    return (
      <div className="max-w-4xl mx-auto">
        <div className="p-6 pb-0 space-y-4">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-lg font-semibold">{labels.draftHeading}</h2>
            {isRegenerating && (
              <div className="flex items-center gap-3 shrink-0">
                <span className="text-xs text-gray-400">regenerating…</span>
                <GenerationClock
                  startedAtIso={generation_started_at}
                  currentAttempt={current_attempt}
                  maxAttempts={max_attempts}
                />
                {/* TODO Phase 3: replace with deep-link to
                    /cancel-<tier> in CC. */}
                <button
                  type="button"
                  disabled
                  className="px-3 py-1 text-xs rounded border border-red-900 text-red-300/60 cursor-not-allowed"
                  title="Open in Claude Code to manage the regeneration"
                  data-testid="generation-stop-button"
                >
                  Open in Claude Code
                </button>
              </div>
            )}
          </div>
          {docMeta}
          <DocumentReviewTabs
            idPrefix="pending-draft"
            document={
              <PendingDraftDocumentTab
                pendingContent={pending_draft.content}
                pendingSummary={pending_draft.change_summary ?? null}
                previousDraftContent={previous_draft_content}
                approvedContent={node.content || null}
                intermediates={auto_revision_intermediates}
                renderers={contentRenderers}
                docKind={docKind}
              />
            }
            extraTabs={extraTabs?.({
              pendingContent: pending_draft.content,
              approvedContent: node.content || null,
            })}
            review={{
              ...reviewProps,
              onSelectionChanged: setReviewSelection,
            }}
          />
          <TelemetryLine telemetry={latest_telemetry} />
        </div>
        <div className="sticky bottom-0 bg-gray-950 border-t border-gray-800 p-4 space-y-3">
          {/* TODO Phase 3: Approve / Reject & Regenerate / AI-revisions
              all migrated to Claude Code skills. The equivalent CC
              entry points are /approve-<tier> <node_id> and
              /regen-<tier>-with-feedback <node_id>. The pending draft
              + AI review render above as read-only. */}
          <div className="flex gap-2 flex-wrap items-center">
            <button
              type="button"
              disabled
              className="px-4 py-2 text-sm rounded border border-gray-700 text-gray-400 cursor-not-allowed"
              title="Approve and regenerate flows have moved to Claude Code skills"
            >
              Open in Claude Code
            </button>
            <span className="text-xs text-gray-500">
              Approve / Reject & Regenerate / AI revisions moved to CC
              skills — invoke /approve-{labels.draftHeading.toLowerCase()}{' '}
              or /regen-{labels.draftHeading.toLowerCase()}-with-feedback
              there.
            </span>
            <CopyButton content={pending_draft.content} />
          </div>
        </div>
      </div>
    );
  }

  // State 4: failed, no content, no pending draft.
  if (generation_status === 'failed' && !node.content) {
    return (
      <div className="p-6 max-w-4xl mx-auto space-y-4">
        {docMeta}
        <div className="p-4 border border-red-800 bg-red-950/40 rounded text-sm text-red-300">
          <div className="font-semibold mb-1">Generation failed</div>
          {last_error && <div className="text-red-400/80">{last_error}</div>}
        </div>
        <div className="flex gap-2 items-center flex-wrap">
          {/* TODO Phase 3: replace with deep-link to /draft-<tier>
              <node_id> in CC. */}
          <button
            type="button"
            disabled
            className="px-4 py-2 text-sm rounded border border-blue-900 text-blue-300/60 cursor-not-allowed"
            title="Retry generation in Claude Code"
          >
            Open in Claude Code
          </button>
          {failed_raw_output && (
            <CopyButton
              content={failed_raw_output}
              label="Copy last response"
              title="Copy the raw LLM output from the last failed attempt to the clipboard"
            />
          )}
        </div>
        <TelemetryLine telemetry={latest_telemetry} />
      </div>
    );
  }

  // State 3: approved content, read-only.
  if (node.content) {
    return (
      <div className="p-6 space-y-4 max-w-4xl mx-auto">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold">{node.name}</h2>
          <span className="text-xs text-gray-500 uppercase tracking-wide shrink-0">
            Approved · read-only
          </span>
        </div>
        {docMeta}
        <DocumentReviewTabs
          idPrefix="approved"
          document={
            <XmlDocument content={node.content} renderers={contentRenderers} />
          }
          extraTabs={extraTabs?.({
            pendingContent: null,
            approvedContent: node.content,
          })}
          review={reviewProps}
        />
        <div className="text-xs text-gray-500 italic">{labels.readOnlyExplanation}</div>
        <div className="flex items-center gap-3">
          <CopyButton content={node.content} />
          <TelemetryLine telemetry={latest_telemetry} />
        </div>
        {projectId && <FeedbackHistory projectId={projectId} nodeId={node.id} />}
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
  // pre-bootstrap empty state. Generation kicks off from CC skills
  // in the new architecture; the dashboard surfaces the empty state
  // and tells the user where to go.
  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <h2 className="text-lg font-semibold">{node.name}</h2>
      {docMeta}
      <div className="text-sm text-gray-400 italic">No approved content yet.</div>
      {/* TODO Phase 3: replace with deep-link to /draft-<tier>
          <node_id> in CC. The Generate button used to enqueue a
          backend job; that route is going away. */}
      <button
        type="button"
        disabled
        className="px-4 py-2 text-sm rounded border border-blue-900 text-blue-300/60 cursor-not-allowed"
        title="Generation happens in Claude Code now — invoke the draft skill there"
      >
        Open in Claude Code
      </button>
    </div>
  );
}
