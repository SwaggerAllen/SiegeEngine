import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useProjectStructure } from '../../hooks/queries/useProjectStructure';
import { DagCanvas } from './DagCanvas';
import { drillElements } from './elements';
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
  componentId: string;
}

/**
 * Per-component decomposition tab. Renders the comp's internal
 * subgraph — local policies, subcomponents, fan-in, every impl leaf
 * — plus the external context layer (top-level feat / resp / policy
 * that trace into this comp).
 *
 * Differences from the project-wide DAG (``FullDagView``):
 * - Element list is comp-scoped via ``drillElements``.
 * - Impl leaves render unconditionally (no reveal-on-click). The
 *   tab is comp-scoped so the impl set is bounded; showing them
 *   up-front matches the user's expectation that decomposition
 *   means "everything underneath."
 * - Double-tap on a subcomponent navigates to that subcomp's
 *   workspace page (``?node=<sub_id>``). Impl / fanin double-taps
 *   navigate to their own pages too.
 */
export function ComponentDecompositionPanel({ projectId, componentId }: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data, isLoading, error } = useProjectStructure(projectId);

  // Show every impl underneath this comp without requiring the user
  // to click each subcomp first. drillElements expects a set of
  // "reveal these subcomps' impl children" ids — feed it every comp
  // id under this scope, including the comp itself for the
  // un-fanned-out case.
  const revealedImplOwners = useMemo(() => {
    if (!data) return new Set<string>();
    const owners = new Set<string>([componentId]);
    for (const n of data.nodes) {
      if (n.tier === 'comp' && n.parent_id === componentId) {
        owners.add(n.id);
      }
    }
    return owners;
  }, [data, componentId]);

  const elements = useMemo(() => {
    if (!data) return [];
    return drillElements(componentId, data.nodes, data.edges, revealedImplOwners);
  }, [data, componentId, revealedImplOwners]);

  const handleDoubleTap = useCallback(
    (nodeId: string) => {
      // Don't navigate to the drilled comp itself — the user is
      // already on it. Other nodes (subcomp / fanin / impl /
      // external context) all have their own workspace pages, so a
      // single ``?node=`` swap routes correctly.
      if (nodeId === componentId) return;
      const next = new URLSearchParams(searchParams);
      next.set('node', nodeId);
      next.delete('view');
      next.delete('hide');
      setSearchParams(next, { replace: false });
    },
    [componentId, searchParams, setSearchParams],
  );

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

  if (elements.length === 0) {
    return (
      <div className="p-6 text-sm text-gray-400">
        No decomposition yet — this component hasn't fanned out into
        subcomponents.
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col">
      {available.length > 0 && (
        <div className="flex items-center px-3 py-1.5 border-b border-gray-800">
          <TierFilterChips
            available={available}
            hidden={hidden}
            onToggle={handleToggleGroup}
          />
        </div>
      )}
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
