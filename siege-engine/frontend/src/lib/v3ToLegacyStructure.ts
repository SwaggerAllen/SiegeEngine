/**
 * Adapter — v3 ``/siege/api/get-project-graph`` response → the legacy
 * ``StructureResponse`` shape the workspace read components consume.
 *
 * The v3 projection omits a bunch of legacy lifecycle flags
 * (has_pending_draft, is_stale, staleness_reasons, generation_running,
 * has_error, needs_user_action, techspec/pubapi node-level slots,
 * is_deferred) — upload-imported projects don't have a generation
 * loop attached. The adapter fills the missing fields with sensible
 * read-only defaults so the existing consumers don't have to branch.
 *
 * Mappings:
 * - tier: feature_expansion→feat, requirements→resp, sysarch→comp,
 *   comparch→comp. The comparch sub-nodes still carry parent_id, so
 *   the topLevelElements filter on ``isTopLevel(n)`` excludes them
 *   from the main DAG view.
 * - Policy nodes (v3 ``kind='policy'``) map to legacy ``tier='policy'``
 *   so the DAG's existing ``policy-top`` styling + layer pinning
 *   picks them up, and the sidebar's ``tier === 'comp'`` filter
 *   doesn't drag them into the Components list.
 * - kind: 'domain' by default; any comp that is the *source* of a
 *   domain_parent edge is marked 'presentational' (mirrors the legacy
 *   sysarch_mint convention).
 * - edge.type → edge.edge_type (field rename only).
 */

import type { ProjectGraph, V3Edge, V3Node } from '../api/siege';
import type { StructureEdge, StructureNode, StructureResponse } from '../api/structure';

const TIER_MAP: Record<string, string> = {
  feature_expansion: 'feat',
  requirements: 'resp',
  sysarch: 'comp',
  comparch: 'comp',
};

function adaptNode(v3: V3Node, presentationalIds: Set<string>): StructureNode {
  // The synthetic project-sysarch root is emitted by the v3
  // projection but doesn't fit the per-substrate tier→legacy mapping;
  // render it as a top-of-DAG comp so FullDagView's topLevelElements
  // picks it up and it lands in the same band as the real comp-tops.
  // Policies share the sysarch tier on the v3 side but the DAG +
  // sidebar treat them as their own legacy tier ('policy').
  let tier: string;
  if (v3.kind === 'sysarch_root') tier = 'comp';
  else if (v3.kind === 'policy') tier = 'policy';
  else tier = TIER_MAP[v3.tier] ?? v3.tier;
  const kind =
    v3.kind === 'policy'
      ? 'policy'
      : tier === 'comp' && presentationalIds.has(v3.id)
        ? 'presentational'
        : 'domain';
  return {
    id: v3.id,
    tier,
    kind,
    parent_id: v3.parent_id,
    name: v3.name,
    display_order: v3.order,
    content: '',
    has_content: v3.has_body,
    has_pending_draft: v3.status === 'drafted',
    generation_running: false,
    has_error: false,
    needs_user_action: false,
    is_stale: false,
    staleness_reasons: [],
    techspec: '',
    pubapi: '',
    is_deferred: false,
  };
}

function adaptEdge(v3: V3Edge): StructureEdge {
  return {
    id: v3.id,
    edge_type: v3.type,
    source_id: v3.source_id,
    target_id: v3.target_id,
  };
}

export function v3ToLegacyStructure(graph: ProjectGraph): StructureResponse {
  const presentationalIds = new Set(
    graph.edges.filter((e) => e.type === 'domain_parent').map((e) => e.source_id),
  );
  return {
    offset: 0, // no event-log offset for upload projects
    nodes: graph.nodes.map((n) => adaptNode(n, presentationalIds)),
    edges: graph.edges.map(adaptEdge),
  };
}
