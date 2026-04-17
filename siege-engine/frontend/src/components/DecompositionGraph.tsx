import { useEffect, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import type cytoscape from 'cytoscape';
import CytoscapeComponent from 'react-cytoscapejs';
import type { StructureEdge, StructureNode, StructureResponse } from '../api/structure';

interface Props {
  graph: StructureResponse;
  projectId: string;
}

/**
 * Read-only Cytoscape rendering of a project's decomposition
 * graph. Structured UI #3 from the Phase 4 roadmap.
 *
 * View semantics:
 * - Top-level comp_* nodes are drawn as larger nodes.
 * - Subcomponent comp_* (parent_id is a comp) are drawn inside
 *   their parent's bounding box via Cytoscape's compound nodes.
 * - Top-level resp_* and subresp_* nodes are drawn as smaller
 *   circles; dashed decomposition edges connect resps to the
 *   components / subcomponents they decompose into.
 * - Dependency edges are solid arrows between comp_* nodes.
 * - Domain_parent edges are dotted arrows from presentational
 *   to domain components.
 *
 * Click-to-navigate: clicking a top-level component navigates
 * to its comparch page. Clicking a subcomponent navigates to
 * its owning top-level's comparch page. Clicking a fan-in node
 * navigates to its owning domain comp's fan-in inspection page.
 * Clicking a resp node selects it without navigation (no resp
 * detail page exists). Structural edits (create/move/delete)
 * are Phase 11.
 */
export function DecompositionGraph({ graph, projectId }: Props) {
  const navigate = useNavigate();
  const cyRef = useRef<cytoscape.Core | null>(null);

  // Resolve a clicked node to the top-level component it belongs
  // to. For a top-level comp that's the node itself. For a
  // subcomponent, walk parent_id to the top-level. For a resp,
  // walk the decomposition edge to its target comp (if any).
  // Returns null if no navigation target exists.
  const topLevelCompIdFor = useMemo(() => {
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    const decompTargetByResp = new Map<string, string>();
    for (const e of graph.edges) {
      if (e.edge_type !== 'decomposition') continue;
      const source = byId.get(e.source_id);
      if (source?.tier === 'resp' && !source.parent_id) {
        // top-level resp → target (usually a top-level comp)
        decompTargetByResp.set(e.source_id, e.target_id);
      }
    }
    return (nodeId: string): string | null => {
      const node = byId.get(nodeId);
      if (!node) return null;
      if (node.tier === 'comp') {
        // Subcomponent: walk parent_id to find the top-level.
        let current: StructureNode | undefined = node;
        while (current && current.parent_id) {
          const parent = byId.get(current.parent_id);
          if (!parent || parent.tier !== 'comp') break;
          current = parent;
        }
        return current?.id ?? null;
      }
      if (node.tier === 'resp') {
        if (node.parent_id) {
          // Subresp: parent is a comp, walk up the same way
          const parent = byId.get(node.parent_id);
          if (parent?.tier === 'comp') {
            // Recurse into the comp walker
            return topLevelCompIdForNode(parent, byId);
          }
        }
        // Top-level resp: follow decomposition edge to its comp
        const target = decompTargetByResp.get(node.id);
        if (target) {
          const targetNode = byId.get(target);
          if (targetNode?.tier === 'comp') {
            return topLevelCompIdForNode(targetNode, byId);
          }
        }
      }
      return null;
    };
  }, [graph]);

  const elements = useMemo(() => {
    return toCytoscapeElements(graph.nodes, graph.edges);
  }, [graph]);

  // Wire up tap handlers once the Cytoscape instance is ready.
  // Clicking a node selects it (Cytoscape's built-in behavior)
  // AND navigates to the resolved top-level component's comparch
  // page if one exists. Clicking on the background deselects.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const byIdLocal = new Map(graph.nodes.map((n) => [n.id, n]));
    const onTap = (event: cytoscape.EventObject) => {
      const target = event.target;
      // event.target is the core itself when tapping the background
      if (target === cy) return;
      if (!target.isNode || !target.isNode()) return;
      const nodeId = target.id();
      const tappedNode = byIdLocal.get(nodeId);
      // Fan-in nodes route to their own inspection page keyed on
      // the owning domain comp (the fan-in's parent_id).
      if (tappedNode?.tier === 'fanin' && tappedNode.parent_id) {
        navigate(
          `/projects/${projectId}/components/${tappedNode.parent_id}/fanin`
        );
        return;
      }
      const compId = topLevelCompIdFor(nodeId);
      if (compId) {
        navigate(`/projects/${projectId}/components/${compId}/comparch`);
      }
    };
    cy.on('tap', onTap);
    return () => {
      cy.off('tap', onTap);
    };
  }, [graph, navigate, projectId, topLevelCompIdFor]);

  const stylesheet = useMemo<cytoscape.StylesheetCSS[]>(
    () => [
      {
        selector: 'node',
        css: {
          'background-color': '#374151',
          'border-width': 1,
          'border-color': '#4b5563',
          label: 'data(name)',
          color: '#e5e7eb',
          'font-size': 10,
          'text-valign': 'center',
          'text-halign': 'center',
          'text-wrap': 'wrap',
          'text-max-width': '120px',
          width: 60,
          height: 28,
          shape: 'round-rectangle',
        },
      },
      {
        selector: 'node[type = "comp-top"]',
        css: {
          'background-color': '#1e3a8a',
          'border-color': '#3b82f6',
          'border-width': 2,
          width: 160,
          height: 60,
          'font-size': 12,
          'font-weight': 'bold',
        },
      },
      {
        selector: 'node[type = "comp-top"][kind = "presentational"]',
        css: {
          'background-color': '#581c87',
          'border-color': '#a855f7',
        },
      },
      {
        selector: 'node[type = "comp-sub"]',
        css: {
          'background-color': '#1f2937',
          'border-color': '#6b7280',
          width: 120,
          height: 40,
        },
      },
      {
        selector: 'node[type = "resp-top"]',
        css: {
          'background-color': '#065f46',
          'border-color': '#10b981',
          shape: 'round-rectangle',
          width: 100,
          height: 28,
          'font-size': 10,
        },
      },
      {
        selector: 'node[type = "resp-sub"]',
        css: {
          'background-color': '#064e3b',
          'border-color': '#059669',
          shape: 'round-rectangle',
          width: 90,
          height: 24,
          'font-size': 9,
        },
      },
      {
        // Phase 7 fan-in synthesis. One per fanned-out domain
        // comp, drawn as a dashed-border hexagon in purple so
        // the bottom-up "as built" artifact reads distinct from
        // the top-down comparch box.
        selector: 'node[type = "fanin"]',
        css: {
          'background-color': '#4c1d95',
          'border-color': '#c4b5fd',
          'border-width': 2,
          'border-style': 'dashed',
          shape: 'hexagon',
          width: 100,
          height: 40,
          'font-size': 10,
          color: '#ede9fe',
        },
      },
      {
        // Phase 6 waiting-on-approval indicator. Any comp_* node
        // with a pending draft on it (subreqs / comparch /
        // subcomparch) gets an amber outline that overrides the
        // kind-specific border color above. Applied via a data
        // attribute so it stacks with the kind selectors.
        selector: 'node[pendingDraftKind]',
        css: {
          'border-color': '#f59e0b',
          'border-width': 4,
        },
      },
      {
        selector: 'edge',
        css: {
          width: 1.5,
          'line-color': '#6b7280',
          'target-arrow-color': '#6b7280',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
        },
      },
      {
        selector: 'edge[edgeType = "decomposition"]',
        css: {
          'line-style': 'dashed',
          'line-color': '#10b981',
          'target-arrow-color': '#10b981',
          width: 1,
        },
      },
      {
        selector: 'edge[edgeType = "dependency"]',
        css: {
          'line-color': '#3b82f6',
          'target-arrow-color': '#3b82f6',
          width: 2,
        },
      },
      {
        selector: 'edge[edgeType = "domain_parent"]',
        css: {
          'line-style': 'dotted',
          'line-color': '#a855f7',
          'target-arrow-color': '#a855f7',
        },
      },
      {
        selector: 'node:selected',
        css: {
          'border-color': '#fbbf24',
          'border-width': 3,
        },
      },
      {
        selector: 'edge:selected',
        css: {
          'line-color': '#fbbf24',
          'target-arrow-color': '#fbbf24',
          width: 3,
        },
      },
    ],
    []
  );

  const layout = useMemo(
    () => ({
      name: 'cose',
      animate: false,
      nodeDimensionsIncludeLabels: true,
      idealEdgeLength: () => 100,
      nodeRepulsion: () => 12000,
      padding: 30,
    }),
    []
  );

  return (
    <div className="w-full h-full cursor-pointer">
      <CytoscapeComponent
        elements={elements}
        stylesheet={stylesheet}
        layout={layout}
        style={{ width: '100%', height: '100%' }}
        cy={(cy) => {
          cyRef.current = cy;
        }}
      />
    </div>
  );
}

/**
 * Walk from a subcomponent comp_* node up to the top-level
 * comp_* ancestor (the one with no comp parent). Used by the
 * click-to-navigate resolver to find which comparch page a
 * clicked subcomponent belongs to.
 */
function topLevelCompIdForNode(
  start: StructureNode,
  byId: Map<string, StructureNode>
): string | null {
  let current: StructureNode | undefined = start;
  while (current && current.parent_id) {
    const parent = byId.get(current.parent_id);
    if (!parent || parent.tier !== 'comp') break;
    current = parent;
  }
  return current?.id ?? null;
}

/**
 * Transform the API payload into the Cytoscape element list
 * (nodes + edges). Marks each node with a ``type`` data field
 * the stylesheet uses for color/size dispatch.
 */
function toCytoscapeElements(
  nodes: StructureNode[],
  edges: StructureEdge[]
): cytoscape.ElementDefinition[] {
  const isCompParent = (parentId: string | null) => {
    if (!parentId) return false;
    const parent = nodes.find((n) => n.id === parentId);
    return parent?.tier === 'comp';
  };

  const nodeElements: cytoscape.ElementDefinition[] = nodes.map((n) => {
    let type: string;
    if (n.tier === 'comp') {
      type = n.parent_id ? 'comp-sub' : 'comp-top';
    } else if (n.tier === 'resp') {
      type = isCompParent(n.parent_id) ? 'resp-sub' : 'resp-top';
    } else if (n.tier === 'fanin') {
      type = 'fanin';
    } else {
      type = 'other';
    }
    // Only emit pendingDraftKind when it's actually set, so the
    // Cytoscape selector ``node[pendingDraftKind]`` only matches
    // comp_* nodes with a waiting draft on them.
    const data: Record<string, string | undefined> = {
      id: n.id,
      name: n.name,
      type,
      kind: n.kind,
      parent: n.tier === 'comp' && n.parent_id ? n.parent_id : undefined,
    };
    if (n.has_pending_draft) {
      // Structure schema replaced the old tier-specific
      // ``pending_draft_kind`` with a boolean ``has_pending_draft``
      // — the stylesheet selector ``node[pendingDraftKind]``
      // only cares that something is pending, not which tier.
      data.pendingDraftKind = 'pending';
    }
    return { data };
  });

  // Edge direction convention: arrows always point from a
  // dependency toward its dependent ("the thing that needs this
  // is over there"). The backend's canonical source/target encodes
  // the *semantic* direction — e.g. a ``dependency`` edge has
  // source=dependent, target=dependency ("billing depends on
  // foundation" → source=billing, target=foundation), and a
  // ``domain_parent`` edge has source=presentational, target=domain
  // ("billing_ui is a primary view into billing" → source=billing_ui,
  // target=billing). For the DAG view, both of those render more
  // intuitively when the arrow runs the other way — from the
  // thing that was built first toward the thing that consumes it.
  // We swap source/target at render time for those two edge types.
  // ``decomposition`` edges are kept as-is: they already point
  // feat→resp / resp→comp, which the user wants preserved.
  const shouldFlipEdgeDirection = (edgeType: string): boolean =>
    edgeType === 'dependency' || edgeType === 'domain_parent';

  const edgeElements: cytoscape.ElementDefinition[] = edges.map((e) => {
    const flipped = shouldFlipEdgeDirection(e.edge_type);
    return {
      data: {
        id: e.id,
        source: flipped ? e.target_id : e.source_id,
        target: flipped ? e.source_id : e.target_id,
        edgeType: e.edge_type,
      },
    };
  });

  return [...nodeElements, ...edgeElements];
}
