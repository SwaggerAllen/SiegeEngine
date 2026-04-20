import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import type { StructureResponse } from '../../api/structure';
import { useErrorLogStore } from '../../store/errorLogStore';
import { structureKeys } from './useProjectStructure';

/**
 * Subscribe to a project's SSE event stream and invalidate
 * TanStack Query cache entries in response.
 *
 * Mount this once per project at layout level
 * (``ProjectWorkspacePage``). Its lifecycle matches the
 * project page; navigating away closes the ``EventSource`` and
 * the server-side asyncio generator unwinds.
 *
 * Flow:
 *
 * 1. Fetch ``/structure`` via ``useProjectStructure`` — that
 *    hook owns the snapshot's freshness.
 * 2. On mount, read the cached snapshot's ``offset`` and open
 *    ``/events/stream?since=<offset>``. The server replays
 *    ring-buffer messages with higher offsets before switching
 *    to live, so no event committed between snapshot read and
 *    subscribe is lost.
 * 3. On each incoming event, invalidate the matching query
 *    keys via the dispatch table below. Every event
 *    invalidates ``structureKeys`` (flags may have flipped);
 *    events carrying a ``node_id`` also invalidate the owning
 *    tier's detail query, resolved from the cached structure.
 * 4. On ``EventSource.onerror`` (network drop, server restart),
 *    log to the error store and let the browser auto-reconnect.
 *    On reconnect, the hook re-subscribes using the latest
 *    cached offset.
 */

interface DeltaPayload {
  offset: number;
  event_type: string;
  node_ids: string[];
}

/**
 * Phase 11 — ephemeral queue-state event types. These don't land
 * in ``graph_events``; they're published directly to SSE
 * subscribers with a negative offset so they never collide with
 * real event offsets. The frontend handler invalidates just the
 * queue list query on these; ``QueueApplied`` additionally
 * invalidates structure + per-tier detail for mutated nodes.
 */
const QUEUE_EVENT_TYPES = new Set([
  'QueueInstructionAppended',
  'QueueInstructionDiscarded',
  'QueueApplying',
  'QueueApplied',
  'QueueFailed',
]);

/**
 * Query keys factory for the Phase 11 pending-change queue.
 * Co-located with the SSE handler so the invalidation seam is
 * visible here; the queue hooks (``useQueueList`` et al.) consume
 * this factory from PR #3.
 */
export const queueKeys = {
  all: ['queue'] as const,
  project: (projectId: string) => ['queue', projectId] as const,
};

export function useProjectEventStream(projectId: string) {
  const queryClient = useQueryClient();
  const pushError = useErrorLogStore((s) => s.pushError);

  useEffect(() => {
    if (!projectId) return;

    // Resolve the "since" offset from the current cached
    // snapshot. If we don't have one yet, start from 0 —
    // /events/stream will replay whatever's in its ring
    // buffer (or live-only if empty).
    const cachedStructure = queryClient.getQueryData<StructureResponse>(
      structureKeys.project(projectId),
    );
    const sinceOffset = cachedStructure?.offset ?? 0;

    const url = `/api/projects/${projectId}/events/stream?since=${sinceOffset}`;
    const es = new EventSource(url);

    const invalidateStructure = () => {
      void queryClient.invalidateQueries({
        queryKey: structureKeys.project(projectId),
      });
    };

    const invalidateTierDetailFor = (nodeId: string) => {
      // Resolve node_id → tier via the cached snapshot. If the
      // cache was invalidated by this event and hasn't refetched
      // yet, skip — the query the user is currently looking at
      // will re-render from the refetched snapshot shortly.
      const snap = queryClient.getQueryData<StructureResponse>(
        structureKeys.project(projectId),
      );
      const node = snap?.nodes.find((n) => n.id === nodeId);
      if (!node) return;
      const key = tierDetailKeyFor(projectId, node, snap?.nodes ?? []);
      if (!key) return;
      void queryClient.invalidateQueries({ queryKey: key });
      // Phase-11 followup B9: the feedback history panel for this
      // node should refresh whenever a new review lands or a new
      // generation job runs against it, so any node-scoped event
      // also invalidates its feedback-history query.
      void queryClient.invalidateQueries({
        queryKey: ['feedbackHistory', projectId, nodeId],
      });
    };

    const invalidateQueueList = () => {
      void queryClient.invalidateQueries({
        queryKey: queueKeys.project(projectId),
      });
    };

    const onDelta = (event: MessageEvent<string>) => {
      let delta: DeltaPayload;
      try {
        delta = JSON.parse(event.data) as DeltaPayload;
      } catch (err) {
        pushError('sse.parse', err);
        return;
      }
      // Phase 11 — ephemeral queue-state events don't touch the
      // structure projection; they only invalidate the queue list.
      // ``QueueApplied`` additionally carries the set of mutated
      // node_ids so tier detail panels refetch.
      if (QUEUE_EVENT_TYPES.has(delta.event_type)) {
        invalidateQueueList();
        if (delta.event_type === 'QueueApplied') {
          invalidateStructure();
          for (const nid of delta.node_ids) {
            invalidateTierDetailFor(nid);
          }
        }
        return;
      }
      // Structure is always invalidated — every event can
      // flip one of its flags (has_pending_draft,
      // has_content, generation_running).
      invalidateStructure();
      // Node-scoped events also invalidate the owning tier's
      // detail query so per-tier panels refetch.
      for (const nid of delta.node_ids) {
        invalidateTierDetailFor(nid);
      }
    };

    const onError = (event: Event) => {
      // EventSource auto-reconnects by default with an
      // exponential backoff roughly ~1s, ~2s, etc. We log the
      // drop so it's visible in the error panel.
      pushError('sse.disconnect', event.type || 'error');
      // When the stream reconnects after a drop, re-seed the
      // structure cache — we may have missed events past the
      // ring buffer's horizon.
      invalidateStructure();
    };

    es.addEventListener('delta', onDelta as EventListener);
    es.addEventListener('error', onError);

    return () => {
      es.removeEventListener('delta', onDelta as EventListener);
      es.removeEventListener('error', onError);
      es.close();
    };
    // queryClient + pushError are stable identities from their
    // respective providers/stores — including them in the dep
    // array is safe and satisfies the lint.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);
}

/**
 * Resolve a node to the TanStack Query key for its tier's
 * detail endpoint, so SSE events can invalidate just that
 * detail query instead of every tier hook.
 *
 * Kept in sync with the individual ``useXxxKeys`` factories by
 * hand — any key-factory shape change will require a matching
 * update here.
 */
function tierDetailKeyFor(
  projectId: string,
  node: { id: string; tier: string; parent_id: string | null },
  allNodes: ReadonlyArray<{ id: string; tier: string; parent_id: string | null }>,
): readonly string[] | null {
  switch (node.tier) {
    case 'expansion':
      return ['expansion', projectId];
    case 'reqs':
      return ['requirements', projectId];
    case 'sysarch':
      return ['sysarch', projectId];
    case 'subreqs':
      // subreqs node's parent_id is the owning comp; the
      // subreqs hook keys on (projectId, compId).
      return node.parent_id ? ['subreqs', projectId, node.parent_id] : null;
    case 'comp':
      if (node.parent_id === null) {
        return ['comparch', projectId, node.id];
      }
      // subcomponent — subcomparch hook keys on
      // (projectId, parentCompId, subId).
      return ['subcomparch', projectId, node.parent_id, node.id];
    case 'fanin':
      // fanin's parent_id is the owning domain comp; the fanin
      // hook keys on (projectId, compId).
      return node.parent_id ? ['fanin', projectId, node.parent_id] : null;
    case 'impl': {
      // impl's parent is either a top-level comp (un-fanned-out
      // case) or a subcomponent. In both cases the impl hook
      // keys on (projectId, ownerId) where ownerId is the
      // direct parent.
      if (!node.parent_id) return null;
      const parent = allNodes.find((n) => n.id === node.parent_id);
      if (!parent) return null;
      return ['impl', projectId, parent.id];
    }
    default:
      // fragments, drafts, and other event types resolve to
      // no tier detail — structure invalidation alone covers
      // them (feat/resp/policy/vocab/ref content lives on the
      // node itself, which the structure refetch will pull).
      return null;
  }
}
