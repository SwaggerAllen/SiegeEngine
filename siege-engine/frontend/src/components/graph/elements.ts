// Pure helpers that transform a StructureResponse into the element
// list consumed by cytoscape + ELK layered layout.
//
// Two modes:
// - `topLevelElements`: the whole-project DAG. Features, top-level
//   responsibilities, top-level policies, top-level components with
//   their dependencies + domain-parent relationships.
// - `drillElements`: a single component's internal subgraph plus its
//   external context (the top-level feat/resp/policy nodes that
//   trace into this component).
//
// Partitioning: each node carries a layoutOptions hint assigning it
// to an ELK partition (feature tier = 0, top-level resp = 1, ...).
// Within a partition the dependency edges drive topological sub-
// layering. ELK reads these via `elk.partitioning.partition`.
//
// Edge direction flipping is kept from the deleted DecompositionGraph:
// dependency and domain_parent edges point source → target in the
// backend but render with the arrow running the other way (toward
// the consumer), which matches the user's mental model of data
// flow. Decomposition and policy_application edges stay as-is.

import type { ElementDefinition } from 'cytoscape';
import type { StructureEdge, StructureNode } from '../../api/structure';

export type NodeType =
  | 'feat'
  | 'resp-top'
  | 'policy-top'
  | 'policy-local'
  | 'comp-top'
  | 'comp-sub'
  | 'fanin'
  | 'impl'
  | 'external-feat'
  | 'external-resp'
  | 'external-policy';

// Partition ordering for the top-level DAG. Lower partitions render
// above higher ones under `elk.direction = DOWN`.
const TOP_LEVEL_PARTITION = {
  feat: 0,
  'resp-top': 1,
  'policy-top': 2,
  'comp-top': 3,
} as const;

// Partition ordering for the drill-in view. External context at the
// top (L0), then local policies, subcomps, fanin, and revealed impl
// leaves at the bottom.
const DRILL_PARTITION = {
  'external-feat': 0,
  'external-resp': 0,
  'external-policy': 0,
  'policy-local': 1,
  'comp-sub': 3,
  fanin: 4,
  impl: 5,
} as const;

/** Edge types whose visual arrow runs opposite to the stored direction. */
const FLIPPED_EDGE_TYPES = new Set(['dependency', 'domain_parent']);

function isTopLevel(n: StructureNode): boolean {
  return n.parent_id === null;
}

function nodeData(
  n: StructureNode,
  type: NodeType,
  partition: number,
): ElementDefinition {
  // ``partition`` lives in ``data`` so the cytoscape-elk extension's
  // ``nodeLayoutOptions(node)`` callback (configured on the layout
  // in ``FullDagView`` / ``EditableGraph``) can read it back via
  // ``node.data('partition')`` and forward it to ELK as
  // ``elk.partitioning.partition``. Putting it on the
  // ``ElementDefinition`` top-level (or in a ``layoutOptions`` field
  // on the element) does not work — cytoscape doesn't propagate
  // unknown element fields to the layout, and cytoscape-elk only
  // reads per-node options via the callback path.
  const data: Record<string, string | number | undefined> = {
    id: n.id,
    name: n.name,
    type,
    kind: n.kind,
    tier: n.tier,
    partition,
  };
  if (n.has_pending_draft) data.pendingDraft = '1';
  if (n.is_stale) data.isStale = '1';
  return { data };
}

function edgeData(e: StructureEdge): ElementDefinition {
  const flipped = FLIPPED_EDGE_TYPES.has(e.edge_type);
  return {
    data: {
      id: e.id,
      source: flipped ? e.target_id : e.source_id,
      target: flipped ? e.source_id : e.target_id,
      edgeType: e.edge_type,
    },
  };
}

/**
 * Top-level DAG view: features, top-level responsibilities,
 * top-level policies, top-level components + every edge among them.
 * Sub-tier nodes (subcomps, fanin, impl) are excluded.
 */
export function topLevelElements(
  nodes: StructureNode[],
  edges: StructureEdge[],
): ElementDefinition[] {
  const kept = new Map<string, NodeType>();
  const elements: ElementDefinition[] = [];

  for (const n of nodes) {
    let type: NodeType | null = null;
    if (n.tier === 'feat') type = 'feat';
    else if (n.tier === 'resp' && isTopLevel(n)) type = 'resp-top';
    else if (n.tier === 'policy' && isTopLevel(n)) type = 'policy-top';
    else if (n.tier === 'comp' && isTopLevel(n)) type = 'comp-top';
    if (type === null) continue;
    kept.set(n.id, type);
    elements.push(nodeData(n, type, TOP_LEVEL_PARTITION[type]));
  }

  for (const e of edges) {
    if (!kept.has(e.source_id) || !kept.has(e.target_id)) continue;
    // Only the four edge types that make sense between these tiers.
    if (
      e.edge_type !== 'decomposition' &&
      e.edge_type !== 'policy_application' &&
      e.edge_type !== 'dependency' &&
      e.edge_type !== 'domain_parent'
    )
      continue;
    elements.push(edgeData(e));
  }

  return elements;
}

/**
 * Reverse-walk from `compId` to find every top-level
 * feat / resp / policy that traces into this component via
 * decomposition or policy_application edges.
 *
 * Walk rules:
 * - `decomposition` edge `resp → comp` with target = compId: the
 *   resp is external context.
 * - `decomposition` edge `feat → resp` where that resp was picked
 *   up above: the feat is external context.
 * - `policy_application` edge `policy → comp` with target = compId:
 *   the policy is external context.
 */
export function externalContextFor(
  compId: string,
  nodes: StructureNode[],
  edges: StructureEdge[],
): StructureNode[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const contextIds = new Set<string>();

  const respSources = new Set<string>();
  for (const e of edges) {
    if (e.edge_type === 'decomposition' && e.target_id === compId) {
      const src = byId.get(e.source_id);
      if (src && src.tier === 'resp' && isTopLevel(src)) {
        respSources.add(src.id);
        contextIds.add(src.id);
      }
    }
    if (e.edge_type === 'policy_application' && e.target_id === compId) {
      const src = byId.get(e.source_id);
      if (src && src.tier === 'policy' && isTopLevel(src)) {
        contextIds.add(src.id);
      }
    }
  }

  for (const e of edges) {
    if (e.edge_type !== 'decomposition') continue;
    if (!respSources.has(e.target_id)) continue;
    const src = byId.get(e.source_id);
    if (src && src.tier === 'feat') contextIds.add(src.id);
  }

  return [...contextIds]
    .map((id) => byId.get(id))
    .filter((n): n is StructureNode => n !== undefined);
}

/**
 * Drill-into-component view. Includes:
 * - External context (reverse-walked feats / resps / policies).
 * - Component-local policies (parent_id = compId, tier = policy).
 * - Subresps (parent_id = compId, tier = resp).
 * - Subcomps (parent_id = compId, tier = comp).
 * - Fan-in node (parent_id = compId, tier = fanin).
 * - Impl leaves for every `revealedImplSubcompId` — clicking a
 *   subcomp in the view adds its impl leaf to the reveal set.
 *   Also includes an impl directly under compId (un-fanned-out
 *   top-level comps own their impl).
 *
 * Edges included: every edge whose both endpoints are in the
 * kept set. This naturally captures the inner dependency / policy
 * / decomposition fabric plus the "outer" arcs that terminate at
 * the drilled comp from external context.
 */
export function drillElements(
  compId: string,
  nodes: StructureNode[],
  edges: StructureEdge[],
  revealedImplSubcompIds: ReadonlySet<string> = new Set(),
): ElementDefinition[] {
  const kept = new Map<string, NodeType>();
  const elements: ElementDefinition[] = [];
  const byId = new Map(nodes.map((n) => [n.id, n]));

  // External context layer.
  for (const n of externalContextFor(compId, nodes, edges)) {
    const type: NodeType =
      n.tier === 'feat'
        ? 'external-feat'
        : n.tier === 'resp'
          ? 'external-resp'
          : 'external-policy';
    kept.set(n.id, type);
    elements.push(nodeData(n, type, DRILL_PARTITION[type]));
  }

  // The drilled comp itself — rendered in the subcomp band so it
  // anchors the internal subgraph visually.
  const comp = byId.get(compId);
  if (comp) {
    kept.set(compId, 'comp-sub');
    elements.push(nodeData(comp, 'comp-sub', DRILL_PARTITION['comp-sub']));
  }

  const subcompIds = new Set<string>();
  for (const n of nodes) {
    if (n.parent_id !== compId) continue;
    if (n.tier === 'policy') {
      kept.set(n.id, 'policy-local');
      elements.push(nodeData(n, 'policy-local', DRILL_PARTITION['policy-local']));
    } else if (n.tier === 'resp') {
      // Pre-Phase-A subresps (tier="resp", parent_id != null) are
      // orphan dead data — the comparch tier no longer mints them
      // and the drill-in graph doesn't surface them.
      continue;
    } else if (n.tier === 'comp') {
      subcompIds.add(n.id);
      kept.set(n.id, 'comp-sub');
      elements.push(nodeData(n, 'comp-sub', DRILL_PARTITION['comp-sub']));
    } else if (n.tier === 'fanin') {
      kept.set(n.id, 'fanin');
      elements.push(nodeData(n, 'fanin', DRILL_PARTITION.fanin));
    } else if (n.tier === 'impl') {
      // Un-fanned-out top-level comp case: impl lives directly
      // under the comp. Reveal iff the comp itself was clicked,
      // modeled here by including compId in the revealed set.
      if (revealedImplSubcompIds.has(compId)) {
        kept.set(n.id, 'impl');
        elements.push(nodeData(n, 'impl', DRILL_PARTITION.impl));
      }
    }
  }

  // Impl leaves under revealed subcomps.
  for (const n of nodes) {
    if (n.tier !== 'impl') continue;
    if (n.parent_id === null || !subcompIds.has(n.parent_id)) continue;
    if (!revealedImplSubcompIds.has(n.parent_id)) continue;
    kept.set(n.id, 'impl');
    elements.push(nodeData(n, 'impl', DRILL_PARTITION.impl));
  }

  // Edges: keep anything with both endpoints in the kept set.
  for (const e of edges) {
    if (!kept.has(e.source_id) || !kept.has(e.target_id)) continue;
    if (
      e.edge_type !== 'decomposition' &&
      e.edge_type !== 'policy_application' &&
      e.edge_type !== 'dependency' &&
      e.edge_type !== 'domain_parent'
    )
      continue;
    elements.push(edgeData(e));
  }

  return elements;
}
