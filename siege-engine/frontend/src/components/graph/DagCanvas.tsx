import { useEffect, useMemo, useRef, useState } from 'react';
import type cytoscape from 'cytoscape';
import type { ElementDefinition, StylesheetCSS } from 'cytoscape';
import CytoscapeComponent from 'react-cytoscapejs';
import { useIsNarrowViewport } from '../../hooks/useMatchMedia';
// Registers cytoscape-elk side-effectfully. Lives here so consumers
// (FullDagView, ComponentDecompositionPanel) get the ELK chunk via
// their own lazy imports without each having to register manually.
import '../../lib/cytoscapeExtensions';
import type { NodeType } from './elements';
import { reachableSets } from './reachable';

interface Props {
  elements: ElementDefinition[];
  stylesheet: StylesheetCSS[];
  /** Called when a node is double-tapped. The id is the cytoscape
   *  node id. Background double-taps are ignored. */
  onNodeDoubleTap?: (nodeId: string) => void;
  /** Tier-filter set: nodes whose ``data.type`` is in this set get
   *  the ``.hidden`` class (display:none) and the layout re-runs so
   *  the visible subset uses the freed space. Empty / undefined
   *  means show everything. */
  hiddenNodeTypes?: ReadonlySet<NodeType>;
}

/**
 * Shared read-only Cytoscape + ELK canvas used by the project-wide
 * DAG view and the per-component decomposition tab. Owns:
 *
 * - ELK layered layout, with direction switching to ``RIGHT`` on
 *   narrow viewports so portrait phones get vertical sibling
 *   columns instead of overflowing horizontal rows.
 * - Selection state — single-tap selects a node; tapping the
 *   background clears.
 * - Reachable-set highlight — selected node lights up its
 *   reachable-down (yellow) and reachable-up (pink) subgraphs;
 *   everything else dims.
 * - Double-tap callback — the only behavior consumers customize.
 *
 * Consumers stay thin: they build the element list and decide
 * what double-tap means in their context (drill / navigate / …).
 */
export function DagCanvas({
  elements,
  stylesheet,
  onNodeDoubleTap,
  hiddenNodeTypes,
}: Props) {
  const cyRef = useRef<cytoscape.Core | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Narrow viewports get a left-to-right layout. See FullDagView's
  // commit history for the original rationale — same hook here so
  // both DAG surfaces rotate together.
  const isNarrow = useIsNarrowViewport();
  const direction = isNarrow ? 'RIGHT' : 'DOWN';
  const layout = useMemo(
    () => ({
      name: 'elk',
      elk: {
        algorithm: 'layered',
        'elk.direction': direction,
        'elk.spacing.nodeNode': 40,
        'elk.layered.spacing.nodeNodeBetweenLayers': 80,
        // INTERACTIVE layering reads each node's
        // ``layerChoiceConstraint`` (set by elements.ts via the
        // computeLayerMap walk) and pins the node to that layer
        // index. Combined with ``interactiveLayout: true`` at the
        // root, this is the documented elkjs path for honoring
        // per-node layer constraints. NETWORK_SIMPLEX (the default
        // layering strategy) silently ignores the constraint, and
        // LONGEST_PATH would re-layer based on path topology
        // independently of our walk. INTERACTIVE is the only
        // strategy that respects the constraint.
        'elk.layered.layering.strategy': 'INTERACTIVE',
        'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
        'elk.interactiveLayout': true,
      },
      nodeDimensionsIncludeLabels: true,
      fit: true,
      padding: 40,
      animate: false,
    }),
    [direction],
  );

  // Cytoscape only runs the layout on mount. Re-run when direction
  // flips after viewport rotation; skip the first run so we don't
  // double-layout on initial mount.
  const directionMounted = useRef(false);
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    if (!directionMounted.current) {
      directionMounted.current = true;
      return;
    }
    cy.layout(layout as unknown as cytoscape.LayoutOptions).run();
  }, [layout]);

  // Reset selection when the element set changes — IDs from a
  // previous element list shouldn't outlive the data they came from.
  useEffect(() => {
    setSelectedId(null);
  }, [elements]);

  // Apply reachable-set highlight classes whenever the selection
  // (or the element set) changes. Single ``cy.batch`` so the repaint
  // is a single render pass.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.elements().removeClass('reachable-down reachable-up dimmed');
      if (!selectedId) return;
      const sets = reachableSets(elements, selectedId);
      cy.nodes().forEach((n) => {
        const id = n.id();
        if (sets.down.has(id)) n.addClass('reachable-down');
        if (sets.up.has(id)) n.addClass('reachable-up');
        if (!sets.down.has(id) && !sets.up.has(id)) n.addClass('dimmed');
      });
      cy.edges().forEach((e) => {
        const id = e.id();
        if (sets.downEdges.has(id)) e.addClass('reachable-down');
        if (sets.upEdges.has(id)) e.addClass('reachable-up');
        if (!sets.downEdges.has(id) && !sets.upEdges.has(id))
          e.addClass('dimmed');
      });
    });
  }, [elements, selectedId]);

  // Tier filter: apply ``.hidden`` to nodes whose data.type is in
  // ``hiddenNodeTypes``, then re-run layout so the visible subset
  // uses the freed space. The stylesheet's ``.hidden`` rule sets
  // ``display: none`` which both hides the node visually and
  // excludes it from the layout pass.
  const hiddenKey = useMemo(
    () => (hiddenNodeTypes ? [...hiddenNodeTypes].sort().join(',') : ''),
    [hiddenNodeTypes],
  );
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.nodes().removeClass('hidden');
      if (!hiddenNodeTypes || hiddenNodeTypes.size === 0) return;
      cy.nodes().forEach((n) => {
        const t = n.data('type') as string | undefined;
        if (t && (hiddenNodeTypes as ReadonlySet<string>).has(t)) {
          n.addClass('hidden');
        }
      });
    });
    cy.layout(layout as unknown as cytoscape.LayoutOptions).run();
    // ``layout`` is referenced here for the relayout call but the
    // effect should re-run only when the *filter set* or element
    // shape changes — direction-driven layout changes are handled
    // by the dedicated direction effect above. Including ``layout``
    // here would relayout twice on viewport rotation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hiddenKey, elements]);

  // Pulse the ``[generating]`` nodes by toggling a ``pulse-on``
  // class on a fixed interval. The stylesheet's two ``[generating]``
  // rules alternate as the class toggles, producing the same
  // attention-grabbing pulse the sidebar tree uses for queued /
  // running jobs. Cytoscape doesn't support CSS animations (canvas
  // renderer), so a plain timer is the simplest way to do this.
  // A toggle on an empty selector is essentially free; no need to
  // gate on whether any generating nodes exist.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const handle = setInterval(() => {
      cy.batch(() => {
        cy.nodes('[generating]').toggleClass('pulse-on');
      });
    }, 600);
    return () => clearInterval(handle);
  }, []);

  // Tap + double-tap handlers.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const onTap = (event: cytoscape.EventObject) => {
      if (event.target === cy) {
        setSelectedId(null);
        return;
      }
      if (!event.target.isNode?.()) return;
      setSelectedId(event.target.id());
    };

    const onDoubleTap = (event: cytoscape.EventObject) => {
      if (!onNodeDoubleTap) return;
      if (event.target === cy) return;
      if (!event.target.isNode?.()) return;
      onNodeDoubleTap(event.target.id());
    };

    cy.on('tap', onTap);
    cy.on('dbltap', onDoubleTap);
    return () => {
      cy.off('tap', onTap);
      cy.off('dbltap', onDoubleTap);
    };
  }, [onNodeDoubleTap]);

  return (
    <CytoscapeComponent
      elements={elements}
      stylesheet={stylesheet}
      layout={layout}
      style={{ width: '100%', height: '100%' }}
      cy={(cy) => {
        cyRef.current = cy;
      }}
    />
  );
}
