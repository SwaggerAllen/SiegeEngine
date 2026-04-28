import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import type cytoscape from 'cytoscape';
import CytoscapeComponent from 'react-cytoscapejs';
import { useProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useIsNarrowViewport } from '../../hooks/useMatchMedia';
// Registers cytoscape-elk side-effectfully. Imported here rather
// than in main.tsx so the heavy ELK bundle only loads alongside
// this component (which itself is lazy-loaded from NavDetail).
import '../../lib/cytoscapeExtensions';
import { drillElements, topLevelElements } from './elements';
import { reachableSets } from './reachable';
import { fullDagStylesheet } from './stylesheet';

interface Props {
  projectId: string;
}

/**
 * Phase 10 layered DAG view. Two modes:
 *
 * - **Top-level** — the whole project's scaffolding DAG. Features,
 *   top-level responsibilities, top-level policies, and top-level
 *   components arranged by `dependency` topology within the comp
 *   band.
 * - **Drill** — a single component's internal subgraph (component-
 *   local policies, subcomps, fan-in, revealed impls)
 *   plus the external-context layer (top-level feat / resp / policy
 *   that trace into this comp).
 *
 * Interaction:
 * - Single tap selects the tapped node and highlights its reachable-
 *   down (yellow) and reachable-up (pink) subgraphs. Background tap
 *   clears.
 * - Double tap on a comp in top-level mode enters drill mode via
 *   `?drill=<comp_id>`. Escape or back button exits drill.
 * - Clicking a subcomp in drill mode reveals its impl leaf inline.
 */
export function FullDagView({ projectId }: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  const drillCompId = searchParams.get('drill');

  const { data, isLoading, error } = useProjectStructure(projectId);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [revealedImpls, setRevealedImpls] = useState<Set<string>>(new Set());

  // Reset local state when the view mode flips. Staying in drill
  // mode but switching which comp is drilled also resets.
  useEffect(() => {
    setSelectedId(null);
    setRevealedImpls(new Set());
  }, [drillCompId]);

  const elements = useMemo(() => {
    if (!data) return [];
    if (drillCompId) {
      return drillElements(drillCompId, data.nodes, data.edges, revealedImpls);
    }
    return topLevelElements(data.nodes, data.edges);
  }, [data, drillCompId, revealedImpls]);

  // Build a quick lookup: which nodes in the current element list
  // are top-level comps? Used for the double-tap drill affordance.
  const topLevelCompIds = useMemo(() => {
    const out = new Set<string>();
    for (const el of elements) {
      const d = (el.data ?? {}) as { id?: string; type?: string };
      if (d.id && d.type === 'comp-top') out.add(d.id);
    }
    return out;
  }, [elements]);

  // Subcomps in the current element list — double-tap on these
  // reveals their impl child inline (when in drill mode).
  const subCompIds = useMemo(() => {
    const out = new Set<string>();
    for (const el of elements) {
      const d = (el.data ?? {}) as { id?: string; type?: string };
      if (d.id && d.type === 'comp-sub') out.add(d.id);
    }
    return out;
  }, [elements]);

  const enterDrill = useCallback(
    (compId: string) => {
      const next = new URLSearchParams(searchParams);
      next.set('drill', compId);
      setSearchParams(next, { replace: false });
    },
    [searchParams, setSearchParams],
  );

  const exitDrill = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    next.delete('drill');
    setSearchParams(next, { replace: false });
  }, [searchParams, setSearchParams]);

  // Escape exits drill. Wired on the view's wrapper so the key
  // only fires while the DAG has the focus chain.
  useEffect(() => {
    if (!drillCompId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') exitDrill();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drillCompId, exitDrill]);

  // Apply reachable-set highlight classes whenever the selection
  // (or the element set) changes. Runs inside `cy.batch()` so a
  // single render pass repaints everything.
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
      if (event.target === cy) return;
      if (!event.target.isNode?.()) return;
      const id = event.target.id();
      if (!drillCompId && topLevelCompIds.has(id)) {
        enterDrill(id);
        return;
      }
      if (drillCompId && subCompIds.has(id)) {
        setRevealedImpls((prev) => {
          if (prev.has(id)) return prev;
          const next = new Set(prev);
          next.add(id);
          return next;
        });
      }
    };

    cy.on('tap', onTap);
    cy.on('dbltap', onDoubleTap);
    return () => {
      cy.off('tap', onTap);
      cy.off('dbltap', onDoubleTap);
    };
  }, [drillCompId, enterDrill, subCompIds, topLevelCompIds]);

  // Narrow viewports (≤768 px) get a left-to-right layout so the
  // tier layers stack horizontally and the wide sibling rows that
  // overflow a portrait phone in DOWN mode become vertical columns
  // that pan instead of wrap.
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
        'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
        'elk.partitioning.activate': true,
      },
      nodeDimensionsIncludeLabels: true,
      fit: true,
      padding: 40,
      animate: false,
    }),
    [direction],
  );

  // Cytoscape only runs the layout on mount; flipping `direction`
  // after that needs an explicit re-layout. Skip the first run so
  // we don't double-layout on initial mount.
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

  if (isLoading) {
    return <div className="p-6 text-sm text-gray-400">Loading graph…</div>;
  }
  if (error || !data) {
    return (
      <div className="p-6 text-sm text-red-400">
        Failed to load the decomposition graph.
      </div>
    );
  }

  const drillLabel = drillCompId
    ? data.nodes.find((n) => n.id === drillCompId)?.name ?? drillCompId
    : null;

  return (
    <div className="h-full w-full flex flex-col">
      <div className="flex items-center gap-3 border-b border-gray-800 px-4 py-2 text-sm text-gray-300">
        {drillCompId ? (
          <>
            <button
              type="button"
              onClick={exitDrill}
              className="px-2 py-0.5 rounded bg-gray-800 hover:bg-gray-700 text-xs"
            >
              ← Back
            </button>
            <span className="text-gray-500">Drilled into</span>
            <span className="font-medium text-gray-100">{drillLabel}</span>
          </>
        ) : (
          <span className="text-gray-400">
            Decomposition DAG — double-click a component to drill in
          </span>
        )}
      </div>
      <div className="flex-1 min-h-0 cursor-pointer">
        <CytoscapeComponent
          elements={elements}
          stylesheet={fullDagStylesheet}
          layout={layout}
          style={{ width: '100%', height: '100%' }}
          cy={(cy) => {
            cyRef.current = cy;
          }}
        />
      </div>
    </div>
  );
}
