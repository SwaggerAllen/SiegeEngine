import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import {
  TIER_NAMES,
  type ResetAllResult,
  type ResumeTierResult,
  type ReviewSweepResult,
  type StructureTierName,
  type TierInfo,
  type TierName,
  getTierInfo,
  resetTier,
  resumeTier,
  reviewSweepTier,
} from '../api/tierOps';
import { TierReviewSummaryPanel } from './TierReviewSummaryPanel';
import { TierStructureSummaryPanel } from './TierStructureSummaryPanel';

/**
 * Tier-ops panel — bulk reset + bulk reject-and-regen per tier.
 *
 * One row per generation tier (the seven BootstrapTierConfig-driven
 * tiers; fanin and reference are out of scope for now). Each row
 * shows the tier's display name, its node count for this project,
 * and two action buttons: Reset All and Regen All from Reviews.
 *
 * Reset All is destructive (deletes downstream nodes, cascades) and
 * double-taps to confirm — same UX as the per-node Reset button on
 * :component:`BootstrapDraftPanel`.
 *
 * Regen All from Reviews fans the per-node "Reject & Regenerate"
 * action across every scope in the tier. Each pending draft's AI
 * review rides forward as ``prior_review_text`` on the new regen,
 * so the model iterates on the prior critique. The post-commit
 * hook on the new draft fires the next AI review automatically —
 * no separate review enqueue is needed. Approved-only scopes are
 * skipped (use Reset All for those).
 *
 * Both endpoints surface skipped scopes. The panel shows a one-
 * line summary on success ("Regen 3 scopes (5 skipped)") so the
 * user can spot a partial sweep.
 */
export function TierOpsPanel({ projectId }: { projectId: string }) {
  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      <header>
        <h2 className="text-lg font-semibold">Tier Operations</h2>
        <p className="text-xs text-gray-400 mt-1">
          Bulk reset every node in a tier and re-run generation from scratch, or
          reject-and-regenerate every pending-draft scope so each one's AI review
          rides forward as feedback. Use sparingly — both fan out across the
          project's downstream cascade.
        </p>
      </header>
      <ul className="divide-y divide-gray-800 border border-gray-800 rounded">
        {TIER_NAMES.map((tier) => (
          <TierRow key={tier} projectId={projectId} tier={tier} />
        ))}
      </ul>
      <ReadOnlyTierSection projectId={projectId} />
    </div>
  );
}

/**
 * Fanin and references don't have BootstrapTierConfig-driven
 * Reset / Review-sweep / Resume operations (their lifecycles
 * differ — fanin writes content directly via FanInContentUpdated,
 * references hang off a different mint path) but they have a
 * structure-summary extractor on the backend, so surface them as
 * a small read-only section below the main grid. Each row only
 * exposes the Structure summary toggle.
 */
function ReadOnlyTierSection({ projectId }: { projectId: string }) {
  return (
    <details className="text-xs" open>
      <summary className="cursor-pointer text-gray-400 hover:text-gray-200 mt-2">
        Read-only tiers (fan-in, references)
      </summary>
      <ul className="divide-y divide-gray-800 border border-gray-800 rounded mt-1">
        <ReadOnlyTierRow
          projectId={projectId}
          tier="fanin"
          tierName="Fan-in"
        />
        <ReadOnlyTierRow
          projectId={projectId}
          tier="references"
          tierName="References"
        />
      </ul>
    </details>
  );
}

function ReadOnlyTierRow({
  projectId,
  tier,
  tierName,
}: {
  projectId: string;
  tier: StructureTierName;
  tierName: string;
}) {
  const [showSummary, setShowSummary] = useState(false);
  return (
    <li className="px-4 py-3 flex flex-col gap-2" data-testid={`tier-row-${tier}`}>
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-gray-100">{tierName}</div>
          <div className="text-xs text-gray-500 mt-0.5">
            Read-only — no Reset / Regen / Resume; structure summary only.
          </div>
        </div>
        <button
          type="button"
          onClick={() => setShowSummary((v) => !v)}
          className="px-3 py-1.5 text-xs rounded border border-gray-700 text-gray-300 hover:bg-gray-800"
          aria-expanded={showSummary}
          data-testid={`tier-row-${tier}-structure-summary-button`}
        >
          {showSummary ? 'Hide structure summary' : 'Structure summary'}
        </button>
      </div>
      {showSummary && <TierStructureSummaryPanel projectId={projectId} tier={tier} />}
    </li>
  );
}

function TierRow({ projectId, tier }: { projectId: string; tier: TierName }) {
  const queryKey = ['tierOps', 'info', projectId, tier];
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery<TierInfo>({
    queryKey,
    queryFn: () => getTierInfo(projectId, tier),
  });
  const [confirming, setConfirming] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  const [showStructure, setShowStructure] = useState(false);
  const [lastResult, setLastResult] = useState<
    | {
        kind: 'reset';
        result: ResetAllResult;
      }
    | {
        kind: 'review';
        result: ReviewSweepResult;
      }
    | {
        kind: 'resume';
        result: ResumeTierResult;
      }
    | { kind: 'error'; text: string }
    | null
  >(null);

  const resetMutation = useMutation({
    mutationFn: () => resetTier(projectId, tier),
    onSuccess: (result) => {
      setConfirming(false);
      setLastResult({ kind: 'reset', result });
      queryClient.invalidateQueries({ queryKey });
      // Other panels' caches may be stale — invalidate broadly.
      queryClient.invalidateQueries({ queryKey: ['structure', projectId] });
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (err instanceof Error ? err.message : String(err));
      setLastResult({ kind: 'error', text: `Reset failed: ${detail}` });
    },
  });

  const reviewMutation = useMutation({
    mutationFn: () => reviewSweepTier(projectId, tier),
    onSuccess: (result) => {
      setLastResult({ kind: 'review', result });
      queryClient.invalidateQueries({ queryKey });
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (err instanceof Error ? err.message : String(err));
      setLastResult({ kind: 'error', text: `Regen sweep failed: ${detail}` });
    },
  });

  const resumeMutation = useMutation({
    mutationFn: () => resumeTier(projectId, tier),
    onSuccess: (result) => {
      setLastResult({ kind: 'resume', result });
      queryClient.invalidateQueries({ queryKey });
      queryClient.invalidateQueries({ queryKey: ['structure', projectId] });
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (err instanceof Error ? err.message : String(err));
      setLastResult({ kind: 'error', text: `Resume failed: ${detail}` });
    },
  });

  const isBusy =
    resetMutation.isPending || reviewMutation.isPending || resumeMutation.isPending;

  return (
    <li className="px-4 py-3 flex flex-col gap-3" data-testid={`tier-row-${tier}`}>
      <div className="flex flex-wrap items-center gap-3">
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-gray-100">
          {data?.tier_name ?? tier}
        </div>
        <div className="text-xs text-gray-500 mt-0.5">
          {isLoading ? (
            'Loading…'
          ) : isError ? (
            <span className="text-red-400">Failed to load tier info</span>
          ) : data ? (
            <>
              {data.node_count} node{data.node_count === 1 ? '' : 's'} ·{' '}
              {data.nodes_with_content} with content
              {data.avg_generation_seconds !== null && (
                <>
                  {' '}
                  · avg gen{' '}
                  <span
                    className="text-gray-300"
                    title={`Mean run-time of ${data.generation_sample_size} completed v2.generate_${tier} job${data.generation_sample_size === 1 ? '' : 's'}; excludes queue wait`}
                  >
                    {formatDuration(data.avg_generation_seconds)}
                  </span>{' '}
                  <span className="text-gray-600">
                    (n={data.generation_sample_size})
                  </span>
                </>
              )}
            </>
          ) : null}
        </div>
        {lastResult && (
          <ResultLine result={lastResult} tier={tier} />
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setShowStructure((v) => !v)}
          disabled={isBusy || (data?.node_count ?? 0) === 0}
          className="px-3 py-1.5 text-xs rounded border border-gray-700 text-gray-300 hover:bg-gray-800 disabled:opacity-40"
          title="Per-node + aggregate metrics for this tier (counts, distributions, ratios)"
          data-testid={`tier-row-${tier}-structure-summary-button`}
          aria-expanded={showStructure}
        >
          {showStructure ? 'Hide structure summary' : 'Structure summary'}
        </button>
        <button
          type="button"
          onClick={() => setShowSummary((v) => !v)}
          disabled={isBusy || (data?.reviewable_count ?? 0) === 0}
          className="px-3 py-1.5 text-xs rounded border border-gray-700 text-gray-300 hover:bg-gray-800 disabled:opacity-40"
          title="Aggregate AI self-review intros + scores for this tier"
          data-testid={`tier-row-${tier}-review-summary-button`}
          aria-expanded={showSummary}
        >
          {showSummary ? 'Hide review summary' : 'Review summary'}
        </button>
        <button
          type="button"
          onClick={() => resumeMutation.mutate()}
          disabled={isBusy || (data?.node_count ?? 0) === 0}
          className="px-3 py-1.5 text-xs rounded border border-emerald-800 text-emerald-300 hover:bg-emerald-950 disabled:opacity-40"
          title="Re-enqueue generation for every scope in this tier whose last attempt was cancelled (skips approved + pending-draft scopes)"
          data-testid={`tier-row-${tier}-resume-button`}
        >
          {resumeMutation.isPending ? 'Resuming…' : 'Resume Tier'}
        </button>
        {data?.supports_review && (
          <button
            type="button"
            onClick={() => reviewMutation.mutate()}
            disabled={isBusy || data.reviewable_count === 0}
            className="px-3 py-1.5 text-xs rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40"
            title="Reject & regenerate every pending-draft scope in this tier; each scope's AI review rides forward as feedback. Approved-only scopes are skipped — use Reset All for those."
            data-testid={`tier-row-${tier}-review-button`}
          >
            {reviewMutation.isPending ? 'Regenerating…' : 'Regen From Reviews'}
          </button>
        )}
        {data?.supports_reset &&
          (confirming ? (
            <>
              <button
                type="button"
                onClick={() => resetMutation.mutate()}
                disabled={isBusy}
                className="px-3 py-1.5 text-xs rounded bg-red-700 hover:bg-red-600 disabled:opacity-40"
                data-testid={`tier-row-${tier}-confirm-reset-button`}
              >
                {resetMutation.isPending
                  ? 'Resetting…'
                  : `Confirm reset · nukes downstream`}
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={isBusy}
                className="px-3 py-1.5 text-xs rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-40"
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              disabled={isBusy || (data?.node_count ?? 0) === 0}
              className="px-3 py-1.5 text-xs rounded border border-red-900 text-red-300 hover:bg-red-950 disabled:opacity-40"
              title="Destructively reset every node in this tier and re-enqueue generation"
              data-testid={`tier-row-${tier}-reset-button`}
            >
              Reset All
            </button>
          ))}
      </div>
      </div>
      {showStructure && <TierStructureSummaryPanel projectId={projectId} tier={tier} />}
      {showSummary && <TierReviewSummaryPanel projectId={projectId} tier={tier} />}
    </li>
  );
}

function ResultLine({
  result,
  tier,
}: {
  result:
    | { kind: 'reset'; result: ResetAllResult }
    | { kind: 'review'; result: ReviewSweepResult }
    | { kind: 'resume'; result: ResumeTierResult }
    | { kind: 'error'; text: string };
  tier: string;
}) {
  if (result.kind === 'error') {
    return (
      <div
        className="text-xs mt-1 text-red-400"
        data-testid={`tier-row-${tier}-message`}
      >
        {result.text}
      </div>
    );
  }
  const skipped = result.result.scopes_skipped;
  const tone = skipped.length > 0 ? 'warn' : 'ok';
  let summary: string;
  if (result.kind === 'reset') {
    summary = skipped.length
      ? `Reset ${result.result.scopes_succeeded} scope${result.result.scopes_succeeded === 1 ? '' : 's'} (${skipped.length} skipped) · ${result.result.jobs_enqueued} generation${result.result.jobs_enqueued === 1 ? '' : 's'} queued.`
      : `Reset ${result.result.scopes_succeeded} scope${result.result.scopes_succeeded === 1 ? '' : 's'} · ${result.result.jobs_enqueued} generation${result.result.jobs_enqueued === 1 ? '' : 's'} queued.`;
  } else if (result.kind === 'resume') {
    const gens = result.result.generations_enqueued;
    const reviews = result.result.reviews_enqueued;
    const parts: string[] = [];
    if (gens > 0) parts.push(`${gens} generation${gens === 1 ? '' : 's'}`);
    if (reviews > 0) parts.push(`${reviews} review${reviews === 1 ? '' : 's'}`);
    const enqueuedText = parts.length === 0 ? 'nothing to resume' : `enqueued ${parts.join(' + ')}`;
    summary = skipped.length
      ? `Resume: ${enqueuedText} (${skipped.length} skipped).`
      : `Resume: ${enqueuedText}.`;
  } else {
    const n = result.result.jobs_enqueued;
    summary = skipped.length
      ? `Regenerated ${n} scope${n === 1 ? '' : 's'} (${skipped.length} skipped).`
      : `Regenerated ${n} scope${n === 1 ? '' : 's'}.`;
  }
  return (
    <div className="mt-1 space-y-1" data-testid={`tier-row-${tier}-message`}>
      <div
        className={`text-xs ${
          tone === 'ok' ? 'text-emerald-400' : 'text-amber-400'
        }`}
      >
        {summary}
      </div>
      {skipped.length > 0 && (
        <details className="text-[10px] text-amber-300/80">
          <summary className="cursor-pointer hover:text-amber-200">
            Show skip reasons
          </summary>
          <ul className="mt-1 ml-3 space-y-0.5 font-mono">
            {skipped.map((s, idx) => (
              <li key={idx}>
                <span className="text-gray-500">[{s.status}]</span>{' '}
                <span className="text-gray-400">{s.scope_ids.join('/') || '(singleton)'}</span>{' '}
                <span className="text-amber-200">
                  {typeof s.detail === 'string' ? s.detail : JSON.stringify(s.detail)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/**
 * Render a duration in seconds as a compact human-readable
 * string. Shorter than ms-precision because the bootstrap chain's
 * generation jobs run on the order of seconds-to-minutes; sub-
 * second precision is meaningless here.
 */
function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const remSeconds = Math.round(seconds - minutes * 60);
  if (minutes < 60) return `${minutes}m ${remSeconds}s`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes - hours * 60;
  return `${hours}h ${remMinutes}m`;
}
