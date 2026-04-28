import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useProjectStructure } from '../../hooks/queries/useProjectStructure';
import { DagCanvas } from './DagCanvas';
import { topLevelElements } from './elements';
import { fullDagStylesheet } from './stylesheet';
import { TierFilterChips } from './TierFilterChips';
import {
  availableGroups,
  expandToTypes,
  parseHiddenParam,
  serializeHiddenParam,
  type TierGroupKey,
} from './tierFilter';

interface Props {
  projectId: string;
}

/**
 * Project-wide read-only DAG. Features, top-level responsibilities,
 * top-level policies, and top-level components arranged by tier
 * partition with dependency topology inside each band.
 *
 * Interaction:
 * - Single tap selects the tapped node and lights up its reachable-
 *   down (yellow) and reachable-up (pink) subgraphs (handled inside
 *   ``DagCanvas``).
 * - Double tap on a top-level component navigates to that
 *   component's workspace page with the Decomposition tab active
 *   (``?node=<comp_id>&view=decomposition``). The per-comp
 *   decomposition view is what was previously the in-place ``?drill``
 *   mode, now folded into the existing comp tabbed page so artifact
 *   tabs (Overview / Comparch / Fan-in / Impl) and the decomposition
 *   share one surface.
 */
export function FullDagView({ projectId }: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data, isLoading, error } = useProjectStructure(projectId);

  const elements = useMemo(() => {
    if (!data) return [];
    return topLevelElements(data.nodes, data.edges);
  }, [data]);

  const topLevelCompIds = useMemo(() => {
    const out = new Set<string>();
    for (const el of elements) {
      const d = (el.data ?? {}) as { id?: string; type?: string };
      if (d.id && d.type === 'comp-top') out.add(d.id);
    }
    return out;
  }, [elements]);

  const available = useMemo(() => availableGroups(elements), [elements]);
  const hidden = useMemo(
    () => parseHiddenParam(searchParams.get('hide')),
    [searchParams],
  );
  const hiddenNodeTypes = useMemo(() => expandToTypes(hidden), [hidden]);
  const handleToggleGroup = useCallback(
    (key: TierGroupKey) => {
      const next = new Set(hidden);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      const params = new URLSearchParams(searchParams);
      const serialized = serializeHiddenParam(next);
      if (serialized) params.set('hide', serialized);
      else params.delete('hide');
      setSearchParams(params, { replace: false });
    },
    [hidden, searchParams, setSearchParams],
  );

  const handleDoubleTap = useCallback(
    (nodeId: string) => {
      if (!topLevelCompIds.has(nodeId)) return;
      const next = new URLSearchParams(searchParams);
      next.set('node', nodeId);
      next.set('view', 'decomposition');
      next.delete('drill');
      setSearchParams(next, { replace: false });
    },
    [searchParams, setSearchParams, topLevelCompIds],
  );

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

  return (
    <div className="h-full w-full flex flex-col">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-gray-800 px-4 py-2 text-sm text-gray-300">
        <span className="text-gray-400">
          Decomposition DAG — double-click a component to open its
          decomposition tab
        </span>
        <div className="ml-auto">
          <TierFilterChips
            available={available}
            hidden={hidden}
            onToggle={handleToggleGroup}
          />
        </div>
      </div>
      <div className="flex-1 min-h-0 cursor-pointer">
        <DagCanvas
          elements={elements}
          stylesheet={fullDagStylesheet}
          onNodeDoubleTap={handleDoubleTap}
          hiddenNodeTypes={hiddenNodeTypes}
        />
      </div>
    </div>
  );
}
