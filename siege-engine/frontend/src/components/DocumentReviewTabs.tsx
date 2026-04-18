import { useState, type ReactNode } from 'react';
import { CollapsibleMarkdown } from './editor/CollapsibleMarkdown';

export type ReviewGenerationStatus = 'idle' | 'running' | 'failed';

export interface ReviewBlockProps {
  reviewText: string;
  reviewStatus: ReviewGenerationStatus;
  reviewLastError: string | null;
  reviewCurrentAttempt: number | null;
  reviewMaxAttempts: number | null;
  onRetryReview?: () => void;
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
 * - ``idle`` + non-empty ``reviewText`` → collapsible
 *   "AI Review" markdown (default collapsed)
 * - ``idle`` + empty ``reviewText`` + ``allowGenerate`` →
 *   "Generate review" CTA
 * - ``idle`` + empty ``reviewText`` + no ``allowGenerate`` →
 *   rendered null
 */
export function ReviewBlock({
  reviewText,
  reviewStatus,
  reviewLastError,
  reviewCurrentAttempt,
  reviewMaxAttempts,
  onRetryReview,
  allowGenerate,
  isBusy,
  emptyGenerateHint = 'No AI review yet — click to run one against this content.',
}: ReviewBlockProps) {
  if (reviewStatus === 'running') {
    const attemptLabel =
      reviewCurrentAttempt && reviewMaxAttempts
        ? ` · attempt ${reviewCurrentAttempt} / ${reviewMaxAttempts}`
        : '';
    return (
      <div
        className="flex items-center gap-3 text-xs text-gray-400"
        data-testid="review-running"
      >
        <div className="h-3 w-3 animate-spin rounded-full border-2 border-gray-600 border-t-blue-400" />
        <span>Reviewing…{attemptLabel}</span>
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
      <div data-testid="review-text">
        <CollapsibleMarkdown className="text-sm text-gray-300 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-gray-200 [&_h2]:mt-2 [&_h2]:mb-1">
          {`# AI Review\n\n${reviewText}`}
        </CollapsibleMarkdown>
      </div>
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
export function DocumentReviewTabs({
  document,
  idPrefix,
  review,
}: {
  document: ReactNode;
  idPrefix: string;
  review: ReviewBlockProps;
}) {
  const [active, setActive] = useState<'document' | 'review'>('document');
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
        {active === 'document' ? (
          <div
            role="tabpanel"
            id={`subtabpanel-${idPrefix}-document`}
            data-testid={`${idPrefix}-document-panel`}
          >
            {document}
          </div>
        ) : (
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
