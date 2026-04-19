// Reachable-set computation over the cytoscape graph.
//
// Given a selected node id, return the set of downstream nodes
// (everything you can reach by following edge.source → edge.target)
// and the set of upstream nodes (everything you can reach by
// following edges in reverse). Used by FullDagView to drive the
// two-colour highlight on single-click selection.
//
// Runs over a flat element list rather than a live cytoscape.Core
// so the function stays pure and testable without a DOM.

import type { ElementDefinition } from 'cytoscape';

export interface ReachableSets {
  /** The selected node + every node reachable via outbound edges. */
  down: Set<string>;
  /** The selected node + every node reachable via inbound edges. */
  up: Set<string>;
  /** Every edge whose both endpoints are in the down-reachable set. */
  downEdges: Set<string>;
  /** Every edge whose both endpoints are in the up-reachable set. */
  upEdges: Set<string>;
}

export function reachableSets(
  elements: ElementDefinition[],
  seedId: string,
): ReachableSets {
  const outgoing = new Map<string, Array<{ to: string; edgeId: string }>>();
  const incoming = new Map<string, Array<{ from: string; edgeId: string }>>();

  for (const el of elements) {
    const data = (el.data ?? {}) as {
      id?: string;
      source?: string;
      target?: string;
    };
    if (data.source === undefined || data.target === undefined) continue;
    const edgeId = data.id ?? `${data.source}_${data.target}`;
    const outBucket = outgoing.get(data.source) ?? [];
    outBucket.push({ to: data.target, edgeId });
    outgoing.set(data.source, outBucket);
    const inBucket = incoming.get(data.target) ?? [];
    inBucket.push({ from: data.source, edgeId });
    incoming.set(data.target, inBucket);
  }

  const down = new Set<string>([seedId]);
  const downEdges = new Set<string>();
  const downStack = [seedId];
  while (downStack.length > 0) {
    const cur = downStack.pop()!;
    for (const { to, edgeId } of outgoing.get(cur) ?? []) {
      downEdges.add(edgeId);
      if (!down.has(to)) {
        down.add(to);
        downStack.push(to);
      }
    }
  }

  const up = new Set<string>([seedId]);
  const upEdges = new Set<string>();
  const upStack = [seedId];
  while (upStack.length > 0) {
    const cur = upStack.pop()!;
    for (const { from, edgeId } of incoming.get(cur) ?? []) {
      upEdges.add(edgeId);
      if (!up.has(from)) {
        up.add(from);
        upStack.push(from);
      }
    }
  }

  return { down, up, downEdges, upEdges };
}
