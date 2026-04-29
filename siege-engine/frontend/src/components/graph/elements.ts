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
// Layering: each node carries an `elk.layered.layering.layerChoiceConstraint`
// computed by `computeLayerMap`. The map is a topological Kahn's BFS
// over the kept edges plus an implicit parent→child edge for every
// node with a parent_id in the kept set. Tier separation falls out of
// path lengths from the sources (feats), and dep edges within a tier
// push depending nodes to deeper layers — so foundation comp lands
// above its dependers, depender chains spread vertically, etc. The
// `INTERACTIVE` layering strategy in DagCanvas reads the constraint
// values back during a second-pass layout run.
//
// Special cases overriding the walk-derived layer:
// - Policy nodes (top-level / external / local) get pinned because
//   they have no decomposition ancestors and the walk would treat
//   them as sources at layer 0.
// - Fan-in nodes are pinned to max-layer + 1 because they synthesize
//   from impls upward but visually belong at the bottom of the comp's
//   internal stack (no incoming edges in the structure).
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

const POLICY_TYPES: ReadonlySet<NodeType> = new Set([
  'policy-top',
  'policy-local',
  'external-policy',
]);

/** Edge types whose visual arrow runs opposite to the stored direction. */
const FLIPPED_EDGE_TYPES = new Set(['dependency', 'domain_parent']);

function isTopLevel(n: StructureNode): boolean {
  return n.parent_id === null;
}

function nodeData(
  n: StructureNode,
  type: NodeType,
  layer: number,
): ElementDefinition {
  const data: Record<string, string | number | undefined> = {
    id: n.id,
    name: n.name,
    type,
    kind: n.kind,
    tier: n.tier,
  };
  if (n.has_pending_draft) data.pendingDraft = '1';
  if (n.is_stale) data.isStale = '1';
  if (n.generation_running) data.generating = '1';
  return {
    data,
    // `layoutOptions` on the element is a cytoscape-elk convention —
    // the extension picks it up and forwards each key as an ELK
    // layoutOption for that node. ``layerChoiceConstraint`` pins
    // this node to the named layer; honored only when the root
    // layout sets ``layering.strategy = INTERACTIVE`` and
    // ``interactiveLayout = true`` (see DagCanvas).
    //
    // @ts-expect-error ElementDefinition doesn't type layoutOptions but
    // cytoscape-elk reads it at runtime.
    layoutOptions: {
      'elk.layered.layering.layerChoiceConstraint': layer,
    },
  };
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

interface KeptNode {
  id: string;
  type: NodeType;
  parent_id: string | null;
}

interface KeptEdge {
  source: string;
  target: string;
}

/**
 * Topological-BFS layer assignment over a kept-node set.
 *
 * For each node, layer = max(layer(parent)) + 1 across:
 * - all incoming "kept" edges (source → target after flipping for
 *   dependency / domain_parent so the arrow's intended consumer is
 *   on the bottom),
 * - the implicit parent_id → child edge (so a subcomp sits below
 *   its drilled-comp parent even when the only structural decomp
 *   edge runs from external resp directly into the subcomp).
 *
 * Sources land at layer 0. Special cases:
 * - Policy nodes are forced to layer 1 (cross-cutting context, no
 *   decomposition ancestor would otherwise place them sensibly).
 * - Fan-in nodes are forced to max-walk-layer + 1 (bottom of the
 *   stack — they have no incoming edges and "represent" the impl
 *   leaves).
 *
 * Cycle-safe: any node still without a layer after Kahn's pass
 * (cycle or disconnected) is assigned 0.
 */
export function computeLayerMap(
  nodes: KeptNode[],
  edges: KeptEdge[],
): Map<string, number> {
  const ids = new Set(nodes.map((n) => n.id));
  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  for (const id of ids) {
    incoming.set(id, []);
    outgoing.set(id, []);
  }

  const addEdge = (src: string, tgt: string) => {
    if (!ids.has(src) || !ids.has(tgt) || src === tgt) return;
    incoming.get(tgt)!.push(src);
    outgoing.get(src)!.push(tgt);
  };

  for (const e of edges) addEdge(e.source, e.target);
  for (const n of nodes) {
    if (n.parent_id) addEdge(n.parent_id, n.id);
  }

  const inDegree = new Map<string, number>();
  for (const [id, parents] of incoming) inDegree.set(id, parents.length);

  const layers = new Map<string, number>();
  const queue: string[] = [];
  for (const [id, deg] of inDegree) {
    if (deg === 0) {
      layers.set(id, 0);
      queue.push(id);
    }
  }

  while (queue.length > 0) {
    const id = queue.shift()!;
    const myLayer = layers.get(id) ?? 0;
    for (const childId of outgoing.get(id) ?? []) {
      const candidate = myLayer + 1;
      const existing = layers.get(childId);
      if (existing === undefined || candidate > existing) {
        layers.set(childId, candidate);
      }
      const newDeg = (inDegree.get(childId) ?? 0) - 1;
      inDegree.set(childId, newDeg);
      if (newDeg === 0) queue.push(childId);
    }
  }

  // Anything still unassigned (cycle or disconnected) → 0.
  for (const id of ids) {
    if (!layers.has(id)) layers.set(id, 0);
  }

  // Special cases.
  let maxLayer = 0;
  for (const v of layers.values()) if (v > maxLayer) maxLayer = v;
  for (const n of nodes) {
    if (POLICY_TYPES.has(n.type)) layers.set(n.id, 1);
    if (n.type === 'fanin') layers.set(n.id, maxLayer + 1);
  }

  return layers;
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
  // Pass 1: pick keepers + their types.
  const keptNodes: { node: StructureNode; type: NodeType }[] = [];
  const keptIds = new Set<string>();
  for (const n of nodes) {
    let type: NodeType | null = null;
    if (n.tier === 'feat') type = 'feat';
    else if (n.tier === 'resp' && isTopLevel(n)) type = 'resp-top';
    else if (n.tier === 'policy' && isTopLevel(n)) type = 'policy-top';
    else if (n.tier === 'comp' && isTopLevel(n)) type = 'comp-top';
    if (type === null) continue;
    keptNodes.push({ node: n, type });
    keptIds.add(n.id);
  }

  // Pass 2: filter edges to the kept set (and to layout-relevant types).
  const keptEdges: { edge: StructureEdge; cyEdge: KeptEdge }[] = [];
  for (const e of edges) {
    if (!keptIds.has(e.source_id) || !keptIds.has(e.target_id)) continue;
    if (
      e.edge_type !== 'decomposition' &&
      e.edge_type !== 'policy_application' &&
      e.edge_type !== 'dependency' &&
      e.edge_type !== 'domain_parent'
    )
      continue;
    const flipped = FLIPPED_EDGE_TYPES.has(e.edge_type);
    keptEdges.push({
      edge: e,
      cyEdge: {
        source: flipped ? e.target_id : e.source_id,
        target: flipped ? e.source_id : e.target_id,
      },
    });
  }

  // Pass 3: layer assignment, then materialize elements with the
  // computed layerChoiceConstraint per node.
  const layerMap = computeLayerMap(
    keptNodes.map(({ node, type }) => ({
      id: node.id,
      type,
      parent_id: node.parent_id,
    })),
    keptEdges.map((k) => k.cyEdge),
  );

  const elements: ElementDefinition[] = [];
  for (const { node, type } of keptNodes) {
    elements.push(nodeData(node, type, layerMap.get(node.id) ?? 0));
  }
  for (const { edge } of keptEdges) {
    elements.push(edgeData(edge));
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
  const byId = new Map(nodes.map((n) => [n.id, n]));

  // Pass 1: pick keepers + their types.
  const keptNodes: { node: StructureNode; type: NodeType }[] = [];
  const keptIds = new Set<string>();
  const push = (node: StructureNode, type: NodeType) => {
    keptNodes.push({ node, type });
    keptIds.add(node.id);
  };

  for (const n of externalContextFor(compId, nodes, edges)) {
    const type: NodeType =
      n.tier === 'feat'
        ? 'external-feat'
        : n.tier === 'resp'
          ? 'external-resp'
          : 'external-policy';
    push(n, type);
  }

  const comp = byId.get(compId);
  if (comp) push(comp, 'comp-sub');

  const subcompIds = new Set<string>();
  for (const n of nodes) {
    if (n.parent_id !== compId) continue;
    if (n.tier === 'policy') {
      push(n, 'policy-local');
    } else if (n.tier === 'resp') {
      // Pre-Phase-A subresps — orphan dead data, not surfaced.
      continue;
    } else if (n.tier === 'comp') {
      subcompIds.add(n.id);
      push(n, 'comp-sub');
    } else if (n.tier === 'fanin') {
      push(n, 'fanin');
    } else if (n.tier === 'impl') {
      // Un-fanned-out top-level comp case: impl lives directly
      // under the comp. Reveal iff the comp itself was clicked,
      // modeled here by including compId in the revealed set.
      if (revealedImplSubcompIds.has(compId)) push(n, 'impl');
    }
  }

  for (const n of nodes) {
    if (n.tier !== 'impl') continue;
    if (n.parent_id === null || !subcompIds.has(n.parent_id)) continue;
    if (!revealedImplSubcompIds.has(n.parent_id)) continue;
    push(n, 'impl');
  }

  // Pass 2: filter edges to the kept set + layout-relevant types.
  const keptEdges: { edge: StructureEdge; cyEdge: KeptEdge }[] = [];
  for (const e of edges) {
    if (!keptIds.has(e.source_id) || !keptIds.has(e.target_id)) continue;
    if (
      e.edge_type !== 'decomposition' &&
      e.edge_type !== 'policy_application' &&
      e.edge_type !== 'dependency' &&
      e.edge_type !== 'domain_parent'
    )
      continue;
    const flipped = FLIPPED_EDGE_TYPES.has(e.edge_type);
    keptEdges.push({
      edge: e,
      cyEdge: {
        source: flipped ? e.target_id : e.source_id,
        target: flipped ? e.source_id : e.target_id,
      },
    });
  }

  // Pass 3: layer assignment + element materialization.
  const layerMap = computeLayerMap(
    keptNodes.map(({ node, type }) => ({
      id: node.id,
      type,
      parent_id: node.parent_id,
    })),
    keptEdges.map((k) => k.cyEdge),
  );

  const elements: ElementDefinition[] = [];
  for (const { node, type } of keptNodes) {
    elements.push(nodeData(node, type, layerMap.get(node.id) ?? 0));
  }
  for (const { edge } of keptEdges) {
    elements.push(edgeData(edge));
  }
  return elements;
}
