import { useMemo, useRef, useState, type ReactNode } from 'react';
import { formatSelectedAsFeedback, parseReview, type ParsedReview } from '../lib/reviewXml';
import { CollapsibleMarkdown } from './editor/CollapsibleMarkdown';
import { GenerationClock } from './GenerationClock';

export type ReviewGenerationStatus = 'idle' | 'running' | 'failed';

export interface ReviewBlockProps {
  reviewText: string;
  reviewStatus: ReviewGenerationStatus;
  reviewLastError: string | null;
  /**
   * ISO-8601 UTC timestamp of when the currently-running review
   * job was enqueued. Drives the review-duration clock — same
   * component the draft generation spinner uses — so review and
   * bootstrap loading states present the same elapsed / started
   * / attempt triple. ``null`` when no review is running.
   */
  reviewStartedAt: string | null;
  reviewCurrentAttempt: number | null;
  reviewMaxAttempts: number | null;
  onRetryReview?: () => void;
  /**
   * Submit a subset of findings back to the tier as feedback.
   * When wired, the structured checkbox UI renders an
   * "Apply selected as feedback" button that calls this with
   * the concatenated text of the checked findings. Only wired
   * on panel branches that regenerate from prose feedback —
   * pending-draft branches in BootstrapDraftPanel. Omitted on
   * approved-content, fan-in, and branches that don't take
   * feedback.
   */
  onApplyFeedback?: (feedbackText: string) => void;
  /**
   * When true the idle-with-empty-review-text case renders a
   * "Generate review" CTA instead of rendering nothing.
   * Callers set this true wherever reviewable content exists
   * (pending draft, approved node content); false in states
   * where kicking off a review wouldn't make sense.
   */
  allowGenerate: boolean;
  isBusy: boolean;
  /**
   * Context-specific copy for the empty-state CTA. Pending-
   * draft and approved-content branches can tune this to match
   * their framing; the fan-in panel has its own wording too.
   */
  emptyGenerateHint?: string;
}

/**
 * Phase 8 — renders the AI self-review panel in one of five
 * states:
 *
 * - ``running`` → spinner + "Reviewing… attempt N/M"
 * - ``failed`` → red error banner + Retry review button
 * - ``idle`` + non-empty ``reviewText`` → structured findings
 *   with checkboxes (and "Apply selected as feedback" when
 *   ``onApplyFeedback`` is wired). Falls back to a collapsible
 *   markdown render for pre-Phase-8 reviews that can't be
 *   parsed into the structured format.
 * - ``idle`` + empty ``reviewText`` + ``allowGenerate`` →
 *   "Generate review" CTA
 * - ``idle`` + empty ``reviewText`` + no ``allowGenerate`` →
 *   rendered null
 */
export function ReviewBlock({
  reviewText,
  reviewStatus,
  reviewLastError,
  reviewStartedAt,
  reviewCurrentAttempt,
  reviewMaxAttempts,
  onRetryReview,
  onApplyFeedback,
  allowGenerate,
  isBusy,
  emptyGenerateHint = 'No AI review yet — click to run one against this content.',
}: ReviewBlockProps) {
  if (reviewStatus === 'running') {
    return (
      <div
        className="flex items-center gap-3 text-xs text-gray-400"
        data-testid="review-running"
      >
        <div className="h-3 w-3 animate-spin rounded-full border-2 border-gray-600 border-t-blue-400" />
        <span>Reviewing…</span>
        <GenerationClock
          startedAtIso={reviewStartedAt}
          currentAttempt={reviewCurrentAttempt}
          maxAttempts={reviewMaxAttempts}
          testId="review-clock"
        />
      </div>
    );
  }
  if (reviewStatus === 'failed') {
    return (
      <div className="space-y-2" data-testid="review-failed">
        <div className="p-3 border border-red-800 bg-red-950/40 rounded text-xs text-red-300">
          <div className="font-semibold mb-1">AI review failed</div>
          {reviewLastError && (
            <div className="text-red-400/80 whitespace-pre-wrap">{reviewLastError}</div>
          )}
        </div>
        {onRetryReview && (
          <button
            type="button"
            onClick={onRetryReview}
            disabled={isBusy}
            className="px-3 py-1 text-xs rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40"
            data-testid="review-retry-button"
          >
            Retry review
          </button>
        )}
      </div>
    );
  }
  if (reviewText.trim()) {
    return (
      <StructuredReview
        reviewText={reviewText}
        onApplyFeedback={onApplyFeedback}
        isBusy={isBusy}
      />
    );
  }
  if (allowGenerate && onRetryReview) {
    return (
      <div className="flex items-center gap-3" data-testid="review-generate">
        <button
          type="button"
          onClick={onRetryReview}
          disabled={isBusy}
          className="px-3 py-1 text-xs rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40"
          data-testid="review-generate-button"
        >
          Generate review
        </button>
        <span className="text-xs text-gray-500">{emptyGenerateHint}</span>
      </div>
    );
  }
  return null;
}

/**
 * Structured checkbox render for a parsed ``<review>`` block.
 * Every finding gets a checkbox; by default all start checked
 * (user selects out, not in — matches "apply the whole review"
 * as the common case). If the XML doesn't parse, falls back to
 * the legacy collapsible-markdown render so pre-Phase-8 reviews
 * keep displaying.
 */
function StructuredReview({
  reviewText,
  onApplyFeedback,
  isBusy,
}: {
  reviewText: string;
  onApplyFeedback?: (feedbackText: string) => void;
  isBusy: boolean;
}) {
  const parsed = useMemo<ParsedReview | null>(() => parseReview(reviewText), [reviewText]);
  const allIds = useMemo(
    () =>
      parsed
        ? [
            ...parsed.handlesStructure.map((f) => f.id),
            ...parsed.architecturalDecisions.map((f) => f.id),
          ]
        : [],
    [parsed],
  );
  // Checkbox state keyed on finding ids. Reset whenever the
  // review text changes so a regenerated review starts with
  // every new finding selected.
  const [selected, setSelected] = useState<Set<string>>(() => new Set(allIds));
  const prevIdsRef = useRef(allIds);
  if (prevIdsRef.current !== allIds) {
    prevIdsRef.current = allIds;
    setSelected(new Set(allIds));
  }

  // Fall back to the legacy markdown render if the review
  // doesn't parse (pre-Phase-8 content, or malformed output
  // that somehow slipped past backend validation).
  if (!parsed) {
    return (
      <div data-testid="review-text-legacy">
        <CollapsibleMarkdown className="text-sm text-gray-300 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-gray-200 [&_h2]:mt-2 [&_h2]:mb-1">
          {`# AI Review\n\n${reviewText}`}
        </CollapsibleMarkdown>
      </div>
    );
  }

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleApply = () => {
    if (!onApplyFeedback) return;
    const feedback = formatSelectedAsFeedback(parsed, selected);
    if (feedback) onApplyFeedback(feedback);
  };

  const selectedCount = selected.size;
  const totalCount = allIds.length;

  return (
    <div className="space-y-4" data-testid="review-text">
      {onApplyFeedback && (
        <div className="flex items-center gap-3 flex-wrap">
          <button
            type="button"
            onClick={handleApply}
            disabled={isBusy || selectedCount === 0}
            className="px-3 py-1 text-xs rounded bg-amber-700 hover:bg-amber-600 disabled:opacity-40"
            title="Regenerate the draft with the selected findings as feedback"
            data-testid="review-apply-button"
          >
            Apply selected as feedback
          </button>
          <span className="text-xs text-gray-500">
            {selectedCount} / {totalCount} selected
          </span>
        </div>
      )}
      <ReviewSection
        heading="Handles & structure"
        findings={parsed.handlesStructure}
        selected={selected}
        onToggle={toggle}
        isBusy={isBusy}
        testId="review-section-handles"
      />
      <ReviewSection
        heading="Architectural decisions"
        findings={parsed.architecturalDecisions}
        selected={selected}
        onToggle={toggle}
        isBusy={isBusy}
        testId="review-section-arch"
      />
    </div>
  );
}

function ReviewSection({
  heading,
  findings,
  selected,
  onToggle,
  isBusy,
  testId,
}: {
  heading: string;
  findings: ReadonlyArray<{ id: string; text: string }>;
  selected: ReadonlySet<string>;
  onToggle: (id: string) => void;
  isBusy: boolean;
  testId: string;
}) {
  return (
    <section data-testid={testId}>
      <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-wide mb-2">
        {heading}
      </h3>
      {findings.length === 0 ? (
        <p className="text-xs text-gray-500 italic">No findings.</p>
      ) : (
        <ul className="space-y-2">
          {findings.map((f) => {
            const checked = selected.has(f.id);
            return (
              <li key={f.id} className="flex gap-2 items-start">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggle(f.id)}
                  disabled={isBusy}
                  className="mt-1 h-3.5 w-3.5 rounded border-gray-600 bg-gray-900 text-blue-500 focus:ring-blue-400 cursor-pointer disabled:opacity-40 shrink-0"
                  aria-label={`Finding ${f.id}`}
                  data-testid={`review-finding-${f.id}`}
                />
                <label
                  onClick={() => !isBusy && onToggle(f.id)}
                  className={`text-sm ${
                    checked ? 'text-gray-200' : 'text-gray-500 line-through'
                  } cursor-pointer`}
                >
                  {f.text}
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/**
 * Document / Review subtabs for the per-tier draft and fan-in
 * panels. Mounted wherever reviewable content exists so the
 * user can flip between the generated XML and the AI review
 * without scrolling.
 *
 * The Review tab carries a small status indicator so in-flight
 * and failed reviews are visible without clicking through:
 * a spinner dot while running, a red dot on failure, nothing
 * otherwise. Default active tab is always Document; the
 * indicator is how the user learns they should click Review.
 */
export interface ExtraTab {
  /** Unique id within this tab strip. Used for aria-controls. */
  id: string;
  /** Label rendered on the tab button. */
  label: string;
  /** Body rendered in the tabpanel when active. */
  content: ReactNode;
}

export function DocumentReviewTabs({
  document,
  idPrefix,
  review,
  extraTabs,
}: {
  document: ReactNode;
  idPrefix: string;
  review: ReviewBlockProps;
  /** Optional extra tabs inserted between Document and Review
   * (left to right in the order supplied). Used by the expansion
   * panel to surface a parsed "Features" list so users don't have
   * to scroll past the introduction paragraph. */
  extraTabs?: ExtraTab[];
}) {
  type TabKey = 'document' | 'review' | `extra:${string}`;
  const [active, setActive] = useState<TabKey>('document');
  const baseClasses =
    'px-3 py-1.5 text-xs border-b-2 -mb-px transition-colors shrink-0 whitespace-nowrap flex items-center gap-2';
  const activeClasses = 'border-blue-500 text-white';
  const idleClasses =
    'border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-600 cursor-pointer';

  const reviewIndicator = (() => {
    if (review.reviewStatus === 'running') {
      return (
        <span
          className="h-2.5 w-2.5 animate-spin rounded-full border-2 border-gray-600 border-t-blue-400"
          data-testid="review-tab-running"
          aria-label="Review running"
        />
      );
    }
    if (review.reviewStatus === 'failed') {
      return (
        <span
          className="h-2 w-2 rounded-full bg-red-500"
          data-testid="review-tab-failed"
          aria-label="Review failed"
        />
      );
    }
    return null;
  })();

  return (
    <div className="flex flex-col" data-testid={`${idPrefix}-tabs`}>
      <nav
        className="border-b border-gray-800 flex items-center gap-1 shrink-0 overflow-x-auto"
        role="tablist"
        aria-label={`${idPrefix} subtabs`}
      >
        <button
          type="button"
          role="tab"
          aria-selected={active === 'document'}
          aria-controls={`subtabpanel-${idPrefix}-document`}
          onClick={() => setActive('document')}
          className={
            active === 'document'
              ? `${baseClasses} ${activeClasses}`
              : `${baseClasses} ${idleClasses}`
          }
        >
          Document
        </button>
        {extraTabs?.map((tab) => {
          const key: TabKey = `extra:${tab.id}`;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={active === key}
              aria-controls={`subtabpanel-${idPrefix}-${tab.id}`}
              onClick={() => setActive(key)}
              className={
                active === key
                  ? `${baseClasses} ${activeClasses}`
                  : `${baseClasses} ${idleClasses}`
              }
              data-testid={`${idPrefix}-${tab.id}-tab`}
            >
              {tab.label}
            </button>
          );
        })}
        <button
          type="button"
          role="tab"
          aria-selected={active === 'review'}
          aria-controls={`subtabpanel-${idPrefix}-review`}
          onClick={() => setActive('review')}
          className={
            active === 'review'
              ? `${baseClasses} ${activeClasses}`
              : `${baseClasses} ${idleClasses}`
          }
          data-testid="review-tab"
        >
          Review
          {reviewIndicator}
        </button>
      </nav>
      <div className="pt-3">
        {active === 'document' && (
          <div
            role="tabpanel"
            id={`subtabpanel-${idPrefix}-document`}
            data-testid={`${idPrefix}-document-panel`}
          >
            {document}
          </div>
        )}
        {extraTabs?.map((tab) => {
          const key: TabKey = `extra:${tab.id}`;
          if (active !== key) return null;
          return (
            <div
              key={tab.id}
              role="tabpanel"
              id={`subtabpanel-${idPrefix}-${tab.id}`}
              data-testid={`${idPrefix}-${tab.id}-panel`}
            >
              {tab.content}
            </div>
          );
        })}
        {active === 'review' && (
          <div
            role="tabpanel"
            id={`subtabpanel-${idPrefix}-review`}
            data-testid={`${idPrefix}-review-panel`}
          >
            <ReviewBlock {...review} />
          </div>
        )}
      </div>
    </div>
  );
}
