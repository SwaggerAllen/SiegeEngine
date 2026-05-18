import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import {
  TIER_NAMES,
  type StructureTierName,
  type TierInfo,
  type TierName,
  getTierInfo,
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
  const { data, isLoading, isError } = useQuery<TierInfo>({
    queryKey,
    queryFn: () => getTierInfo(projectId, tier),
  });
  const [showSummary, setShowSummary] = useState(false);
  const [showStructure, setShowStructure] = useState(false);

  // Phase 3 migration: Reset All / Regen From Reviews / Resume Tier /
  // Regen below threshold all moved to Claude Code skills. The
  // dashboard keeps the per-tier counts + structure / review summary
  // toggles; bulk actions render as Open-in-CC disabled buttons.
  // TODO Phase 3: deep-link each disabled button to its CC skill:
  //   - Reset All           → /reset-tier <tier>
  //   - Regen From Reviews  → /regen-tier-from-reviews <tier>
  //   - Resume Tier         → /resume-tier <tier>
  //   - Regen below thr.    → /regen-below <tier> <threshold> <mode>
  const isBusy = false;

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
          disabled
          className="px-3 py-1.5 text-xs rounded border border-emerald-800 text-emerald-300/60 cursor-not-allowed"
          title="Resume Tier moved to Claude Code — invoke /resume-tier <tier> there"
          data-testid={`tier-row-${tier}-resume-button`}
        >
          Open in Claude Code · Resume
        </button>
        {data?.supports_review && (
          <button
            type="button"
            disabled
            className="px-3 py-1.5 text-xs rounded border border-blue-800 text-blue-200/60 cursor-not-allowed"
            title="Regen From Reviews moved to Claude Code — invoke /regen-tier-from-reviews <tier> there"
            data-testid={`tier-row-${tier}-review-button`}
          >
            Open in Claude Code · Regen From Reviews
          </button>
        )}
        {data?.supports_reset && (
          <button
            type="button"
            disabled
            className="px-3 py-1.5 text-xs rounded border border-red-900 text-red-300/60 cursor-not-allowed"
            title="Reset All moved to Claude Code — invoke /reset-tier <tier> there"
            data-testid={`tier-row-${tier}-reset-button`}
          >
            Open in Claude Code · Reset All
          </button>
        )}
      </div>
      {data?.supports_review && (
        <div
          className="flex flex-wrap items-center gap-2 text-xs text-gray-400"
          data-testid={`tier-row-${tier}-threshold-row`}
        >
          <span>
            Regen below threshold: invoke{' '}
            <code className="bg-gray-900 px-1">/regen-below {tier} &lt;threshold&gt; &lt;mode&gt;</code>{' '}
            in Claude Code.
          </span>
        </div>
      )}
      </div>
      {showStructure && <TierStructureSummaryPanel projectId={projectId} tier={tier} />}
      {showSummary && <TierReviewSummaryPanel projectId={projectId} tier={tier} />}
    </li>
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
