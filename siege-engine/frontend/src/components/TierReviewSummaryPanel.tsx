import { useCallback, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  getTierReviewSummary,
  type TierName,
  type TierReviewSummary,
} from '../api/tierOps';

interface Props {
  projectId: string;
  tier: TierName;
}

/**
 * Read-only per-tier review-summary dashboard. Aggregates every
 * approved draft's parsed AI-self-review into a copy-paste-ready
 * block for prompt iteration.
 *
 * Layout, top to bottom:
 *
 * 1. Header counts (reviewed / missing / total).
 * 2. Score histogram (4 buckets, simple horizontal bars).
 * 3. Stats line (min · mean · median · max).
 * 4. Worst-N slider + "score < X" threshold filter.
 * 5. Copy-paste markdown block — pre-formatted reviews, score-
 *    ordered, capped by the slider/threshold. Copy-to-clipboard
 *    button.
 * 6. Per-review compact list with scope label, score, finding
 *    counts.
 * 7. Missing list (collapsible) — scopes whose review couldn't be
 *    summarised, with the reason.
 *
 * Reviews come back from the backend already sorted worst-first so
 * the slider just slices the prefix.
 */
export function TierReviewSummaryPanel({ projectId, tier }: Props) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['tierReviewSummary', projectId, tier],
    queryFn: () => getTierReviewSummary(projectId, tier),
  });

  if (isLoading) {
    return (
      <div className="text-xs text-gray-500 italic" data-testid={`tier-review-summary-${tier}`}>
        Loading review summary…
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div
        className="text-xs text-red-400"
        data-testid={`tier-review-summary-${tier}`}
      >
        Failed to load review summary
        {error instanceof Error ? `: ${error.message}` : ''}
      </div>
    );
  }
  return <SummaryBody summary={data} tier={tier} />;
}

function SummaryBody({ summary, tier }: { summary: TierReviewSummary; tier: TierName }) {
  const [worstN, setWorstN] = useState<number>(() => Math.min(10, summary.reviews.length));
  const [threshold, setThreshold] = useState<number | null>(null);

  const filteredReviews = useMemo(() => {
    let pool = summary.reviews;
    if (threshold !== null) {
      pool = pool.filter((r) => r.score < threshold);
    }
    return pool.slice(0, worstN);
  }, [summary.reviews, worstN, threshold]);

  const copyBlock = useMemo(() => formatCopyBlock(summary, filteredReviews), [summary, filteredReviews]);

  if (summary.reviewed_count === 0 && summary.missing_count === 0) {
    return (
      <div
        className="text-xs text-gray-500 italic"
        data-testid={`tier-review-summary-${tier}`}
      >
        No drafts in this tier yet — review summary will populate after
        approvals land.
      </div>
    );
  }

  return (
    <div
      className="space-y-3 rounded border border-gray-800 bg-gray-950/40 p-3"
      data-testid={`tier-review-summary-${tier}`}
    >
      <Header summary={summary} />
      {summary.score_stats && (
        <>
          <Histogram summary={summary} />
          <StatsLine summary={summary} />
        </>
      )}
      {summary.reviews.length > 0 && (
        <>
          <FilterRow
            total={summary.reviews.length}
            worstN={worstN}
            setWorstN={setWorstN}
            threshold={threshold}
            setThreshold={setThreshold}
            filteredCount={filteredReviews.length}
          />
          <CopyBlock content={copyBlock} tier={tier} />
          <ReviewList reviews={filteredReviews} tier={tier} />
        </>
      )}
      {summary.missing.length > 0 && <MissingList missing={summary.missing} tier={tier} />}
    </div>
  );
}

function Header({ summary }: { summary: TierReviewSummary }) {
  return (
    <div className="text-xs text-gray-300">
      <span className="font-semibold text-gray-100">{summary.tier_name}</span>
      <span className="text-gray-500">
        {' '}
        — {summary.reviewed_count} reviewed
        {summary.missing_count > 0 ? ` · ${summary.missing_count} missing` : ''}
        {' '}of {summary.draft_count}
      </span>
    </div>
  );
}

function Histogram({ summary }: { summary: TierReviewSummary }) {
  const buckets: Array<{ label: string; count: number; tone: string }> = [
    { label: '0–30', count: summary.score_buckets.band_0_30, tone: 'bg-red-700' },
    { label: '31–60', count: summary.score_buckets.band_31_60, tone: 'bg-amber-700' },
    { label: '61–85', count: summary.score_buckets.band_61_85, tone: 'bg-green-700' },
    { label: '86–100', count: summary.score_buckets.band_86_100, tone: 'bg-green-500' },
  ];
  const max = Math.max(...buckets.map((b) => b.count), 1);
  return (
    <div className="space-y-1" data-testid="tier-review-summary-histogram">
      {buckets.map((b) => (
        <div key={b.label} className="flex items-center gap-2 text-[11px] text-gray-400">
          <span className="w-12 text-right tabular-nums">{b.label}</span>
          <div className="flex-1 bg-gray-900 h-3 rounded overflow-hidden">
            <div
              className={`h-full ${b.tone}`}
              style={{ width: `${(b.count / max) * 100}%` }}
            />
          </div>
          <span className="w-6 text-right tabular-nums text-gray-200">{b.count}</span>
        </div>
      ))}
    </div>
  );
}

function StatsLine({ summary }: { summary: TierReviewSummary }) {
  if (!summary.score_stats) return null;
  const stats = summary.score_stats;
  return (
    <div className="text-[11px] text-gray-400" data-testid="tier-review-summary-stats">
      <span className="text-gray-500">scores</span> · min {stats.min} · mean{' '}
      {stats.mean.toFixed(1)} · median {stats.median.toFixed(0)} · max {stats.max}
      {summary.handles_count_mean !== null && summary.arch_count_mean !== null && (
        <>
          {' '}
          · <span className="text-gray-500">findings/review</span> ·{' '}
          handles {summary.handles_count_mean.toFixed(1)} · arch{' '}
          {summary.arch_count_mean.toFixed(1)}
        </>
      )}
    </div>
  );
}

function FilterRow({
  total,
  worstN,
  setWorstN,
  threshold,
  setThreshold,
  filteredCount,
}: {
  total: number;
  worstN: number;
  setWorstN: (n: number) => void;
  threshold: number | null;
  setThreshold: (n: number | null) => void;
  filteredCount: number;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-[11px] text-gray-400">
      <label className="flex items-center gap-2">
        <span>Worst</span>
        <input
          type="range"
          min={1}
          max={total}
          value={worstN}
          onChange={(e) => setWorstN(parseInt(e.target.value, 10))}
          className="w-32"
          data-testid="tier-review-summary-worst-n"
        />
        <span className="tabular-nums w-8 text-right text-gray-200">{worstN}</span>
      </label>
      <label className="flex items-center gap-2">
        <span>Score &lt;</span>
        <input
          type="number"
          min={0}
          max={100}
          value={threshold ?? ''}
          placeholder="all"
          onChange={(e) => {
            const v = e.target.value.trim();
            setThreshold(v === '' ? null : Math.max(0, Math.min(100, parseInt(v, 10))));
          }}
          className="w-16 bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-gray-200"
          data-testid="tier-review-summary-threshold"
        />
      </label>
      <span className="text-gray-500">showing {filteredCount}</span>
    </div>
  );
}

function CopyBlock({ content, tier }: { content: string; tier: TierName }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [content]);
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-wider text-gray-500">
          Copy-paste block
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className="px-2 py-0.5 text-xs rounded border border-gray-700 text-gray-400 hover:bg-gray-800 hover:text-gray-200"
          data-testid={`tier-review-summary-copy-${tier}`}
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre
        className="bg-gray-950 border border-gray-800 rounded p-2 text-[11px] text-gray-300 max-h-72 overflow-auto whitespace-pre-wrap"
        data-testid={`tier-review-summary-copy-block-${tier}`}
      >
        {content || '(no reviews match the current filter)'}
      </pre>
    </div>
  );
}

function ReviewList({
  reviews,
  tier,
}: {
  reviews: TierReviewSummary['reviews'];
  tier: TierName;
}) {
  return (
    <details className="text-[11px]">
      <summary className="cursor-pointer text-gray-400 hover:text-gray-200">
        Per-review detail ({reviews.length})
      </summary>
      <ul
        className="mt-1 space-y-0.5 m-0 pl-0 list-none"
        data-testid={`tier-review-summary-list-${tier}`}
      >
        {reviews.map((r) => (
          <li
            key={r.scope_id}
            className="flex items-baseline gap-2 text-gray-300"
          >
            <span className="font-mono text-gray-500 w-12 tabular-nums">{r.score}</span>
            <span className="font-semibold text-gray-200">{r.scope_label}</span>
            <span className="text-gray-500">
              · h{r.handles_count} · a{r.arch_count}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function MissingList({
  missing,
  tier,
}: {
  missing: TierReviewSummary['missing'];
  tier: TierName;
}) {
  return (
    <details className="text-[11px]">
      <summary className="cursor-pointer text-gray-400 hover:text-gray-200">
        Missing ({missing.length})
      </summary>
      <ul
        className="mt-1 space-y-0.5 m-0 pl-0 list-none"
        data-testid={`tier-review-summary-missing-${tier}`}
      >
        {missing.map((m) => (
          <li key={m.scope_id} className="flex items-baseline gap-2 text-gray-300">
            <span className="font-semibold text-gray-200">{m.scope_label}</span>
            <span className="text-gray-500">— {m.reason}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function formatCopyBlock(
  summary: TierReviewSummary,
  reviews: TierReviewSummary['reviews'],
): string {
  if (reviews.length === 0) return '';
  const header = `# ${summary.tier_name} — ${reviews.length} review${reviews.length === 1 ? '' : 's'}`;
  const sections = reviews.map((r) => {
    const lines = [
      `## ${r.scope_label} — score ${r.score}`,
      r.intro.trim(),
      `findings: ${r.handles_count} handles · ${r.arch_count} arch`,
    ];
    return lines.join('\n');
  });
  return [header, ...sections].join('\n\n');
}
