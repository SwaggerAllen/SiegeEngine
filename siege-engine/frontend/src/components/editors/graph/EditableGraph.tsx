import { useEffect, useMemo, useRef } from 'react';
import type cytoscape from 'cytoscape';
import CytoscapeComponent from 'react-cytoscapejs';
import type { ElementDefinition, StylesheetCSS } from 'cytoscape';
// Registers cytoscape-elk side-effectfully. Shared with FullDagView.
import '../../../lib/cytoscapeExtensions';
import type {
  EditableGraphSelection,
  SelectionState,
} from './useEditableGraphSelection';

/**
 * Thin wrapper around react-cytoscapejs for the Phase 11 edit
 * surfaces (Dependency / Domain-parent / Decomposition editors).
 *
 * Responsibilities:
 *
 * - Render the Cytoscape canvas with ELK layout.
 * - Forward Cytoscape tap events to the caller's selection hook
 *   (`onNodeTap`, `onEdgeTap`, `onBackgroundTap`).
 * - Apply selection-state classes (`selected-source`,
 *   `candidate-target`, `invalid-target`, `non-candidate`,
 *   `selected-edge`) imperatively via `cy.batch()` whenever the
 *   state or element set changes.
 * - Re-layout on ELK-relevant changes (new nodes / edges) via a
 *   `layoutKey` prop so callers can opt into re-layout when
 *   material additions happen.
 *
 * The caller owns:
 *
 * - Building `elements` from the structure snapshot.
 * - Supplying `canConnect(src, tgt)` so the selection hook knows
 *   which targets are valid.
 * - Supplying `candidates(sourceId)` returning the set of node IDs
 *   that should be styled as candidates (usually "everything
 *   connectable per canConnect"). Nodes neither selected nor in
 *   the candidate set get `non-candidate` (dimmed).
 * - Dispatching the actual `AddDependency` / `RemoveDependency`
 *   (etc.) instructions when the user confirms.
 *
 * Not a drop-in replacement for `FullDagView` — that component
 * keeps its own code path because it's read-only + adds the
 * reachable-set highlights. `EditableGraph` is the read-write
 * variant for the edit panels.
 */
export interface EditableGraphProps {
  elements: ElementDefinition[];
  stylesheet: StylesheetCSS[];
  selection: EditableGraphSelection;
  /** Given the current source, return the set of node IDs that
   * should be highlighted as candidate targets. Everything outside
   * the union (source ∪ candidates ∪ invalids) gets `non-candidate`
   * (dimmed) styling. */
  candidates?: (sourceId: string) => Set<string>;
  /** Given the current source, return the set of node IDs that
   * *would* be candidates but are blocked by a rule (cycle, parent
   * cap, etc.). Overlay on top of `candidates`. */
  invalidTargets?: (sourceId: string) => Set<string>;
  /** ELK layout override; defaults to a `layered` DOWN layout
   * matching FullDagView. Pass your own to change direction or
   * spacing. */
  layout?: Record<string, unknown>;
  /** Opaque key — when this changes, the graph is relayed out.
   * Use for material structural changes that ELK should re-fit. */
  layoutKey?: string;
}

const DEFAULT_LAYOUT = {
  name: 'elk',
  elk: {
    algorithm: 'layered',
    'elk.direction': 'DOWN',
    'elk.spacing.nodeNode': 40,
    'elk.layered.spacing.nodeNodeBetweenLayers': 80,
    'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
    'elk.partitioning.activate': true,
  },
  nodeDimensionsIncludeLabels: true,
  fit: true,
  padding: 40,
  animate: false,
};

const ALL_CLASSES =
  'selected-source candidate-target invalid-target non-candidate selected-edge';

export function EditableGraph({
  elements,
  stylesheet,
  selection,
  candidates,
  invalidTargets,
  layout,
  layoutKey,
}: EditableGraphProps) {
  const cyRef = useRef<cytoscape.Core | null>(null);
  const resolvedLayout = useMemo(() => layout ?? DEFAULT_LAYOUT, [layout]);

  // Apply selection-state classes whenever state / elements change.
  // Callers are expected to ``useCallback`` their ``candidates`` /
  // ``invalidTargets`` predicates so we don't re-run on every
  // render.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    applySelectionClasses(cy, selection.state, candidates, invalidTargets);
  }, [selection.state, elements, candidates, invalidTargets]);

  // Wire tap / background / edge-tap handlers.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const onTap = (event: cytoscape.EventObject) => {
      if (event.target === cy) {
        selection.onBackgroundTap();
        return;
      }
      if (event.target.isNode?.()) {
        selection.onNodeTap(event.target.id());
        return;
      }
      if (event.target.isEdge?.()) {
        selection.onEdgeTap(event.target.id());
      }
    };

    cy.on('tap', onTap);
    return () => {
      cy.off('tap', onTap);
    };
  }, [selection]);

  // Re-run layout on `layoutKey` change. ELK only auto-fits on
  // initial mount; structural edits need an explicit re-layout.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    if (layoutKey === undefined) return;
    cy.layout(resolvedLayout as unknown as cytoscape.LayoutOptions).run();
  }, [layoutKey, resolvedLayout]);

  return (
    <div className="h-full w-full" data-testid="editable-graph">
      <CytoscapeComponent
        elements={elements}
        stylesheet={stylesheet}
        layout={resolvedLayout as unknown as cytoscape.LayoutOptions}
        style={{ width: '100%', height: '100%' }}
        cy={(cy) => {
          cyRef.current = cy;
        }}
      />
    </div>
  );
}

function applySelectionClasses(
  cy: cytoscape.Core,
  state: SelectionState,
  candidates: ((sourceId: string) => Set<string>) | undefined,
  invalidTargets: ((sourceId: string) => Set<string>) | undefined,
) {
  cy.batch(() => {
    cy.elements().removeClass(ALL_CLASSES);
    if (state.kind === 'idle') return;
    if (state.kind === 'edge-tapped') {
      const edge = cy.$id(state.edgeId);
      if (edge.length) edge.addClass('selected-edge');
      return;
    }
    const sourceId =
      state.kind === 'source-selected' || state.kind === 'edge-staged'
        ? state.sourceId
        : null;
    if (!sourceId) return;
    const source = cy.$id(sourceId);
    if (source.length) source.addClass('selected-source');
    const candidateSet = candidates?.(sourceId) ?? new Set<string>();
    const invalidSet = invalidTargets?.(sourceId) ?? new Set<string>();
    cy.nodes().forEach((n) => {
      const id = n.id();
      if (id === sourceId) return;
      if (invalidSet.has(id)) {
        n.addClass('invalid-target');
        return;
      }
      if (candidateSet.has(id)) {
        n.addClass('candidate-target');
        return;
      }
      n.addClass('non-candidate');
    });
    if (state.kind === 'edge-staged') {
      // Emphasize the staged target.
      const target = cy.$id(state.targetId);
      if (target.length) {
        target.removeClass('candidate-target non-candidate');
        target.addClass('selected-source');
      }
    }
  });
}
