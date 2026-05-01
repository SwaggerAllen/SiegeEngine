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
  | 'comp-top-presentational'
  | 'comp-sub'
  | 'fanin'
  | 'impl'
  | 'external-feat'
  | 'external-resp'
  | 'external-policy';

// Types whose layer is independent of graph topology — they sit on
// fixed top rows regardless of how the BFS walk would place them.
// Without this, an orphan resp (no decomposition edge from a feat)
// would land at layer 0 (source) and render in the feature row;
// the same for policies, which have no decomposition ancestors at
// all. Pinning them keeps the upstream tiers honest.
const FIXED_TOP_LAYER: Partial<Record<NodeType, number>> = {
  feat: 0,
  'external-feat': 0,
  'resp-top': 1,
  'external-resp': 1,
  'policy-top': 1,
  'policy-local': 1,
  'external-policy': 1,
};

// Types pinned to the bottom of the layout — one row below the
// deepest walk-derived layer. Presentational comps live here
// (their own band, separate from the dep-spread domain comp band)
// and fanin nodes (drill view only; synthesize from impls upward
// but visually anchor the bottom of the comp's internal stack).
const FIXED_BOTTOM_TYPES: ReadonlySet<NodeType> = new Set([
  'comp-top-presentational',
  'fanin',
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
 * For each non-pinned node, layer = max(layer(parent)) + 1 across:
 * - all incoming "kept" edges (source → target after flipping for
 *   dependency / domain_parent so the arrow's intended consumer is
 *   on the bottom),
 * - the implicit parent_id → child edge (so a subcomp sits below
 *   its drilled-comp parent even when the only structural decomp
 *   edge runs from external resp directly into the subcomp).
 *
 * Sources without a fixed pin land at layer 0. Two sets of pins
 * override the walk:
 * - ``FIXED_TOP_LAYER`` types (feat / resp / policy) lock to a
 *   canonical top row independently of their incoming edges.
 *   Without this, an orphan resp lands in the feature row and a
 *   resp with weird ancestry lands in some third row. Pinning is
 *   applied at processing time so descendants see the pinned
 *   position, not the would-have-been walked position.
 * - ``FIXED_BOTTOM_TYPES`` (comp-top-presentational, fanin) get
 *   pushed to one row below the deepest walk-derived layer of any
 *   non-bottom node. This puts presentational components in their
 *   own band below the dep-spread domain comps, and anchors fan-in
 *   nodes at the bottom of the drill view.
 *
 * Cycle-safe: any node still without a layer after Kahn's pass
 * (cycle or disconnected) is assigned 0.
 */
export function computeLayerMap(
  nodes: KeptNode[],
  edges: KeptEdge[],
): Map<string, number> {
  const ids = new Set(nodes.map((n) => n.id));
  const typeById = new Map<string, NodeType>();
  for (const n of nodes) typeById.set(n.id, n.type);

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

  // Kahn's BFS. Each node's layer is decided when it's processed
  // (after all its parents). FIXED_TOP_LAYER values override the
  // walk-derived value AT processing time so descendants see the
  // pinned position, not the would-have-been walked position.
  const layers = new Map<string, number>();
  const queue: string[] = [];
  for (const [id, deg] of inDegree) {
    if (deg === 0) queue.push(id);
  }

  while (queue.length > 0) {
    const id = queue.shift()!;
    const type = typeById.get(id);
    const fixed = type !== undefined ? FIXED_TOP_LAYER[type] : undefined;

    let myLayer: number;
    if (fixed !== undefined) {
      myLayer = fixed;
    } else {
      const parentIds = incoming.get(id) ?? [];
      myLayer = 0;
      for (const pid of parentIds) {
        const pl = layers.get(pid) ?? 0;
        if (pl + 1 > myLayer) myLayer = pl + 1;
      }
    }
    layers.set(id, myLayer);

    for (const childId of outgoing.get(id) ?? []) {
      const newDeg = (inDegree.get(childId) ?? 0) - 1;
      inDegree.set(childId, newDeg);
      if (newDeg === 0) queue.push(childId);
    }
  }

  // Anything still unassigned (cycle or disconnected) → 0.
  for (const id of ids) {
    if (!layers.has(id)) layers.set(id, 0);
  }

  // Bottom-pin overrides. Compute the deepest walk-derived layer
  // EXCLUDING the bottom-pinned types so the floor reflects the
  // domain content's depth, not the bottom band's own layer, then
  // pin every bottom-type node to one row below.
  let maxLayer = 0;
  for (const n of nodes) {
    if (FIXED_BOTTOM_TYPES.has(n.type)) continue;
    const v = layers.get(n.id) ?? 0;
    if (v > maxLayer) maxLayer = v;
  }
  for (const n of nodes) {
    if (FIXED_BOTTOM_TYPES.has(n.type)) layers.set(n.id, maxLayer + 1);
  }

  return layers;
}

/**
 * Top-level DAG view: features, top-level responsibilities,
 * top-level policies, top-level components + every edge among them.
 * Sub-tier nodes (subcomps, fanin, impl) are excluded.
 *
 * Top-level comps are typed by ``kind``: ``comp-top`` for domain,
 * ``comp-top-presentational`` for presentational. The presentational
 * type pins to its own row at the bottom of the layout (see
 * ``FIXED_BOTTOM_TYPES``) so the two kinds visually separate.
 *
 * ``policy_application`` edges whose target is a subcomp get rolled
 * up to the subcomp's top-level ancestor — a policy that applies
 * inside one of this comp's subcomps still belongs to that comp's
 * picture, and the alternative (filtering the edge out) leaves the
 * policy floating disconnected.
 */
export function topLevelElements(
  nodes: StructureNode[],
  edges: StructureEdge[],
): ElementDefinition[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));

  // Pass 1: pick keepers + their types.
  const keptNodes: { node: StructureNode; type: NodeType }[] = [];
  const keptIds = new Set<string>();
  for (const n of nodes) {
    let type: NodeType | null = null;
    if (n.tier === 'feat') type = 'feat';
    else if (n.tier === 'resp' && isTopLevel(n)) type = 'resp-top';
    else if (n.tier === 'policy' && isTopLevel(n)) type = 'policy-top';
    else if (n.tier === 'comp' && isTopLevel(n)) {
      type = n.kind === 'presentational' ? 'comp-top-presentational' : 'comp-top';
    }
    if (type === null) continue;
    keptNodes.push({ node: n, type });
    keptIds.add(n.id);
  }

  // Walk parent_id chains to find the first ancestor in the kept
  // set. Used to roll a policy_application edge's target up from
  // a subcomp to its top-level comp ancestor when only the
  // ancestor is in scope for this view.
  const rollUpToKept = (nodeId: string): string | null => {
    let current = byId.get(nodeId);
    while (current) {
      if (keptIds.has(current.id)) return current.id;
      if (!current.parent_id) return null;
      current = byId.get(current.parent_id);
    }
    return null;
  };

  // Pass 2: filter edges to the kept set (and to layout-relevant types).
  const keptEdges: { edge: StructureEdge; cyEdge: KeptEdge }[] = [];
  // Dedup roll-ups: when multiple subcomps share a parent and the
  // same policy applies to several of them, the rollup would emit
  // duplicate parent-edges. Cytoscape tolerates them but they
  // visually clutter; key by ``source/target/edgeType``.
  const seenRolledEdges = new Set<string>();
  for (const e of edges) {
    if (
      e.edge_type !== 'decomposition' &&
      e.edge_type !== 'policy_application' &&
      e.edge_type !== 'dependency' &&
      e.edge_type !== 'domain_parent'
    )
      continue;

    const sourceId = e.source_id;
    let targetId = e.target_id;
    let isRolledUp = false;
    if (e.edge_type === 'policy_application' && !keptIds.has(targetId)) {
      const rolled = rollUpToKept(targetId);
      if (rolled === null) continue;
      targetId = rolled;
      isRolledUp = true;
    }
    if (!keptIds.has(sourceId) || !keptIds.has(targetId)) continue;

    if (isRolledUp) {
      const key = `${sourceId}::${targetId}::${e.edge_type}`;
      if (seenRolledEdges.has(key)) continue;
      seenRolledEdges.add(key);
    }

    const flipped = FLIPPED_EDGE_TYPES.has(e.edge_type);
    const cySource = flipped ? targetId : sourceId;
    const cyTarget = flipped ? sourceId : targetId;
    keptEdges.push({
      edge: isRolledUp
        ? // Synthesize a derived edge so edgeData renders the
          // rolled-up source/target instead of the originals.
          { ...e, source_id: sourceId, target_id: targetId }
        : e,
      cyEdge: { source: cySource, target: cyTarget },
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
