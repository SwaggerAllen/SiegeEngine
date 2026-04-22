import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { DraftDiffView } from '../components/DraftDiffView';
import { StructuredDraftDiffView } from '../components/StructuredDraftDiffView';
import {
  useAcceptReviewNodeMutation,
  useCloseReviewBatchMutation,
  useReviewBatch,
  useReviewBatchNodeDiff,
  useReviewBatchNodes,
} from '../hooks/queries/useReviewBatch';
import type { StaleNodeItem } from '../api/review';
import type { DraftDocKind } from '../lib/extractDraftSections';
import { describeApiError } from '../lib/describeApiError';

/**
 * Phase 12 batched-review walker page.
 *
 * Three-panel layout mounted at ``/projects/:id/review/:batchId``:
 *
 * 1. Top bar — batch metadata + Close button.
 * 2. Left rail — stale nodes at the batch's pinned offset,
 *    ordered roughly upstream-to-downstream, with
 *    destructive/non-destructive dot badges.
 * 3. Main pane — per-node content diff + per-fragment accordion.
 *
 * Accept controls render but are unwired in 12c; the accept
 * endpoint + its destructive/non-destructive branching land in
 * 12d.
 */
export function ReviewBatchPage() {
  const { id: projectId, batchId } = useParams<{ id: string; batchId: string }>();
  if (!projectId || !batchId) return null;
  return <WalkerShell projectId={projectId} batchId={batchId} />;
}

function WalkerShell({
  projectId,
  batchId,
}: {
  projectId: string;
  batchId: string;
}) {
  const navigate = useNavigate();
  const batchQuery = useReviewBatch(projectId, batchId);
  const nodesQuery = useReviewBatchNodes(projectId, batchId);
  const closeMutation = useCloseReviewBatchMutation(projectId, batchId);

  const items = useMemo(() => nodesQuery.data ?? [], [nodesQuery.data]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Default to the first stale node once the list loads.
  const effectiveSelectedId =
    selectedId ?? (items.length > 0 ? items[0].node_id : null);

  if (batchQuery.isLoading) {
    return (
      <div className="p-6 text-gray-400 text-sm">Loading review batch…</div>
    );
  }
  if (batchQuery.error) {
    return (
      <div className="p-6 text-red-400 text-sm">
        {describeApiError(batchQuery.error, 'Failed to load review batch')}
      </div>
    );
  }
  const batch = batchQuery.data;
  if (!batch) return null;

  const batchIsClosed = Boolean(batch.closed_at);

  return (
    <div className="h-screen flex flex-col bg-gray-900 text-white overflow-hidden">
      <header className="border-b border-gray-700 px-3 py-2 flex items-center gap-3 shrink-0">
        <Link
          to={`/projects/${projectId}`}
          className="text-sm text-gray-400 hover:text-white shrink-0"
        >
          ← Workspace
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-sm font-bold truncate">
            Review batch
            <span className="text-gray-500 font-normal">
              {' '}
              · pinned @ offset {batch.pinned_offset} · {items.length}{' '}
              stale node{items.length === 1 ? '' : 's'}
            </span>
          </h1>
        </div>
        {batchIsClosed ? (
          <span className="text-xs text-gray-500 uppercase tracking-wide">
            Closed · read-only
          </span>
        ) : (
          <button
            type="button"
            onClick={() => {
              closeMutation.mutate(undefined, {
                onSuccess: () => navigate(`/projects/${projectId}`),
              });
            }}
            disabled={closeMutation.isPending}
            className="px-3 py-1 text-xs rounded border border-gray-700 hover:bg-gray-800 disabled:opacity-40"
          >
            Close batch
          </button>
        )}
      </header>

      <div className="flex-1 flex min-h-0">
        <aside
          className="w-72 shrink-0 border-r border-gray-700 bg-gray-950 overflow-y-auto"
          aria-label="Stale nodes in this batch"
        >
          {nodesQuery.isLoading ? (
            <p className="p-3 text-xs text-gray-500 italic">Loading nodes…</p>
          ) : items.length === 0 ? (
            <p className="p-3 text-xs text-gray-500 italic">
              Nothing stale in this batch.
            </p>
          ) : (
            <ul className="divide-y divide-gray-800">
              {items.map((item) => (
                <StaleNodeRow
                  key={item.node_id}
                  item={item}
                  selected={item.node_id === effectiveSelectedId}
                  onSelect={() => setSelectedId(item.node_id)}
                />
              ))}
            </ul>
          )}
        </aside>

        <main
          className="flex-1 overflow-y-auto"
          aria-label="Review detail"
        >
          {effectiveSelectedId ? (
            <NodeDiffPane
              projectId={projectId}
              batchId={batchId}
              nodeId={effectiveSelectedId}
              item={items.find((i) => i.node_id === effectiveSelectedId)}
              batchIsClosed={batchIsClosed}
              onAccepted={() => setSelectedId(null)}
            />
          ) : (
            <div className="p-6 text-sm text-gray-500 italic">
              No stale node selected — the walker is empty for this batch.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

/**
 * Tier → structured-diff kind. Only the three structured
 * bootstrap docs have section-aware parsing; other tiers fall
 * through to the flat :component:`DraftDiffView`.
 */
function docKindForTier(tier: string): DraftDocKind | null {
  if (tier === 'expansion') return 'expansion';
  if (tier === 'reqs') return 'requirements';
  if (tier === 'sysarch') return 'sysarch';
  return null;
}

function StaleNodeRow({
  item,
  selected,
  onSelect,
}: {
  item: StaleNodeItem;
  selected: boolean;
  onSelect: () => void;
}) {
  const dotClass = item.is_destructive
    ? 'bg-red-500'
    : 'bg-blue-500';
  const dotLabel = item.is_destructive ? 'Destructive' : 'Non-destructive';
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className={`w-full text-left px-3 py-2 hover:bg-gray-800 ${
          selected ? 'bg-gray-800' : ''
        }`}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`inline-block w-2 h-2 rounded-full ${dotClass} shrink-0`}
            aria-label={dotLabel}
            title={dotLabel}
          />
          <span className="text-sm truncate flex-1" title={item.name}>
            {item.name}
          </span>
          <span className="text-[10px] uppercase tracking-wide text-gray-500 shrink-0">
            {item.tier}
          </span>
        </div>
        <div className="mt-1 text-[11px] text-gray-500 truncate">
          {item.reasons.join(' · ')}
        </div>
      </button>
    </li>
  );
}

function NodeDiffPane({
  projectId,
  batchId,
  nodeId,
  item,
  batchIsClosed,
  onAccepted,
}: {
  projectId: string;
  batchId: string;
  nodeId: string;
  item: StaleNodeItem | undefined;
  batchIsClosed: boolean;
  onAccepted: () => void;
}) {
  const diffQuery = useReviewBatchNodeDiff(projectId, batchId, nodeId);
  const acceptMutation = useAcceptReviewNodeMutation(projectId, batchId);

  if (diffQuery.isLoading) {
    return (
      <div className="p-6 text-sm text-gray-400">Loading node diff…</div>
    );
  }
  if (diffQuery.error) {
    return (
      <div className="p-6 text-sm text-red-400">
        {describeApiError(diffQuery.error, 'Failed to load node diff')}
      </div>
    );
  }
  const diff = diffQuery.data;
  if (!diff) return null;

  return (
    <div className="p-6 space-y-5 max-w-5xl">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">{item?.name ?? nodeId}</h2>
        {item && (
          <p className="text-xs text-gray-500">
            {item.tier} · {item.reasons.join(', ')}
            {item.is_destructive && (
              <span className="ml-2 inline-block px-1.5 py-0.5 rounded bg-red-900/60 text-red-300 uppercase text-[10px] tracking-wide">
                Destructive
              </span>
            )}
          </p>
        )}
      </header>

      <section className="space-y-2">
        <h3 className="text-xs uppercase tracking-wide text-gray-400">
          Node content
        </h3>
        {item && docKindForTier(item.tier) ? (
          <StructuredDraftDiffView
            before={diff.node_content.before}
            after={diff.node_content.after ?? ''}
            kind={docKindForTier(item.tier) as DraftDocKind}
            label="Comparing pinned snapshot against live content."
          />
        ) : (
          <DraftDiffView
            before={diff.node_content.before}
            after={diff.node_content.after ?? ''}
            label="Comparing pinned snapshot against live content."
          />
        )}
      </section>

      <section className="space-y-3">
        <h3 className="text-xs uppercase tracking-wide text-gray-400">
          Fragments ({diff.fragments.length})
        </h3>
        {diff.fragments.length === 0 ? (
          <p className="text-xs text-gray-500 italic">
            No fragments owned by this node.
          </p>
        ) : (
          diff.fragments.map((frag) => (
            <details
              key={frag.fragment_kind}
              className="border border-gray-800 rounded"
            >
              <summary className="px-3 py-2 text-sm cursor-pointer hover:bg-gray-900">
                <code className="text-xs">{frag.fragment_kind}</code>
              </summary>
              <div className="p-3 border-t border-gray-800">
                <DraftDiffView
                  before={frag.before}
                  after={frag.after ?? ''}
                />
              </div>
            </details>
          ))
        )}
      </section>

      <section className="pt-4 border-t border-gray-800 space-y-2">
        <h3 className="text-xs uppercase tracking-wide text-gray-400">
          Accept
        </h3>
        <p className="text-xs text-gray-500">
          {item?.is_destructive
            ? 'This node was affected by a destructive structural change. Accepting will release the halted cascade by regenerating this node; downstream stale nodes follow via the normal fanout.'
            : 'The upstream change was non-destructive and the downstream cascade already fired. Accepting just clears the stale marker on this node.'}
        </p>
        <div className="flex gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => {
              acceptMutation.mutate(nodeId, { onSuccess: onAccepted });
            }}
            disabled={batchIsClosed || acceptMutation.isPending}
            className={`px-3 py-1 text-xs rounded ${
              item?.is_destructive
                ? 'bg-red-800 hover:bg-red-700 text-white'
                : 'bg-green-700 hover:bg-green-600 text-white'
            } disabled:opacity-40`}
          >
            {item?.is_destructive ? 'Accept — release cascade' : 'Accept changes'}
          </button>
        </div>
        {acceptMutation.isSuccess && (
          <p className="text-[11px] text-gray-400 italic">
            Accepted ·{' '}
            {acceptMutation.data?.regen_job_ids.length
              ? `enqueued ${acceptMutation.data.regen_job_ids.length} regen job${
                  acceptMutation.data.regen_job_ids.length === 1 ? '' : 's'
                }`
              : 'no new regens fired'}
            .
          </p>
        )}
        {acceptMutation.error && (
          <p className="text-[11px] text-red-400">
            {describeApiError(acceptMutation.error, 'Accept failed')}
          </p>
        )}
        {batchIsClosed && (
          <p className="text-[11px] text-gray-500 italic">
            This batch is closed; accept is disabled.
          </p>
        )}
      </section>
    </div>
  );
}
