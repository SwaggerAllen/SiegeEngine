import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import {
  TIER_NAMES,
  type TierInfo,
  type TierName,
  getTierInfo,
  resetTier,
  reviewSweepTier,
} from '../api/tierOps';

/**
 * Tier-ops panel — bulk reset + bulk AI-review per tier.
 *
 * One row per generation tier (the seven BootstrapTierConfig-driven
 * tiers; fanin and reference are out of scope for now). Each row
 * shows the tier's display name, its node count for this project,
 * and two action buttons: Reset All and Review All.
 *
 * Reset is destructive and double-tap to confirm — same UX as the
 * per-node Reset button on :component:`BootstrapDraftPanel`.
 * Review sweep is non-destructive and fires on the first click.
 *
 * Both endpoints surface skipped scopes (e.g. a node that was never
 * approved, or a tier with no content yet to review). The panel
 * shows a one-line summary on success ("Reset 3 scopes (2
 * skipped)") so the user can spot a partial sweep.
 */
export function TierOpsPanel({ projectId }: { projectId: string }) {
  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      <header>
        <h2 className="text-lg font-semibold">Tier Operations</h2>
        <p className="text-xs text-gray-400 mt-1">
          Bulk reset every node in a tier and re-run generation, or sweep a fresh AI
          self-review across every approved node. Use sparingly — both fan out across
          the project's downstream cascade.
        </p>
      </header>
      <ul className="divide-y divide-gray-800 border border-gray-800 rounded">
        {TIER_NAMES.map((tier) => (
          <TierRow key={tier} projectId={projectId} tier={tier} />
        ))}
      </ul>
    </div>
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
  const [lastMessage, setLastMessage] = useState<{
    tone: 'ok' | 'warn' | 'err';
    text: string;
  } | null>(null);

  const resetMutation = useMutation({
    mutationFn: () => resetTier(projectId, tier),
    onSuccess: (result) => {
      setConfirming(false);
      const skipped = result.scopes_skipped.length;
      const ok = result.scopes_succeeded;
      setLastMessage({
        tone: skipped > 0 ? 'warn' : 'ok',
        text: skipped
          ? `Reset ${ok} scope${ok === 1 ? '' : 's'} (${skipped} skipped) · ${result.jobs_cancelled} jobs cancelled.`
          : `Reset ${ok} scope${ok === 1 ? '' : 's'} · ${result.jobs_cancelled} jobs cancelled.`,
      });
      queryClient.invalidateQueries({ queryKey });
      // Other panels' caches may be stale — invalidate broadly.
      queryClient.invalidateQueries({ queryKey: ['structure', projectId] });
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (err instanceof Error ? err.message : String(err));
      setLastMessage({ tone: 'err', text: `Reset failed: ${detail}` });
    },
  });

  const reviewMutation = useMutation({
    mutationFn: () => reviewSweepTier(projectId, tier),
    onSuccess: (result) => {
      const skipped = result.scopes_skipped.length;
      const enqueued = result.jobs_enqueued;
      setLastMessage({
        tone: skipped > 0 ? 'warn' : 'ok',
        text: skipped
          ? `Enqueued ${enqueued} review${enqueued === 1 ? '' : 's'} (${skipped} skipped).`
          : `Enqueued ${enqueued} review${enqueued === 1 ? '' : 's'}.`,
      });
      queryClient.invalidateQueries({ queryKey });
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (err instanceof Error ? err.message : String(err));
      setLastMessage({ tone: 'err', text: `Review sweep failed: ${detail}` });
    },
  });

  const isBusy = resetMutation.isPending || reviewMutation.isPending;

  return (
    <li className="px-4 py-3 flex flex-wrap items-center gap-3" data-testid={`tier-row-${tier}`}>
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
            </>
          ) : null}
        </div>
        {lastMessage && (
          <div
            className={`text-xs mt-1 ${
              lastMessage.tone === 'ok'
                ? 'text-emerald-400'
                : lastMessage.tone === 'warn'
                  ? 'text-amber-400'
                  : 'text-red-400'
            }`}
            data-testid={`tier-row-${tier}-message`}
          >
            {lastMessage.text}
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {data?.supports_review && (
          <button
            type="button"
            onClick={() => reviewMutation.mutate()}
            disabled={isBusy || data.nodes_with_content === 0}
            className="px-3 py-1.5 text-xs rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40"
            title="Enqueue a fresh AI self-review for every node in this tier with content"
            data-testid={`tier-row-${tier}-review-button`}
          >
            {reviewMutation.isPending ? 'Reviewing…' : 'Review All'}
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
    </li>
  );
}
