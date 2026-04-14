import { useMemo } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import type {
  DecompositionGraphEdge,
  DecompositionGraphNode,
  DecompositionGraphResponse,
} from '../api/decomposition';

interface Props {
  graph: DecompositionGraphResponse;
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
 * No interactivity beyond click-to-select. Editing the graph
 * (create/move/delete) is Phase 11 structural-edit territory
 * and lands in a follow-up phase on top of this view.
 */
export function DecompositionGraph({ graph }: Props) {
  const elements = useMemo(() => {
    return toCytoscapeElements(graph.nodes, graph.edges);
  }, [graph]);

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
    <div className="w-full h-full">
      <CytoscapeComponent
        elements={elements}
        stylesheet={stylesheet}
        layout={layout}
        style={{ width: '100%', height: '100%' }}
      />
    </div>
  );
}

/**
 * Transform the API payload into the Cytoscape element list
 * (nodes + edges). Marks each node with a ``type`` data field
 * the stylesheet uses for color/size dispatch.
 */
function toCytoscapeElements(
  nodes: DecompositionGraphNode[],
  edges: DecompositionGraphEdge[]
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
    } else {
      type = 'other';
    }
    return {
      data: {
        id: n.id,
        name: n.name,
        type,
        kind: n.kind,
        parent:
          n.tier === 'comp' && n.parent_id ? n.parent_id : undefined,
      },
    };
  });

  const edgeElements: cytoscape.ElementDefinition[] = edges.map((e) => ({
    data: {
      id: e.id,
      source: e.source_id,
      target: e.target_id,
      edgeType: e.edge_type,
    },
  }));

  return [...nodeElements, ...edgeElements];
}
