import { useCallback, useMemo } from 'react';
import type { ElementDefinition } from 'cytoscape';
import type { Instruction } from '../../api/queue';
import type { StructureNode, StructureEdge } from '../../api/structure';
import { useEnqueueInstructionMutation } from '../../hooks/mutations/useQueueMutations';
import { fullDagStylesheet } from '../graph/stylesheet';
import { reachableSets } from '../graph/reachable';
import { EditableGraph } from './graph/EditableGraph';
import { editStylesheet } from './graph/editStylesheet';
import {
  NodeActionSidebar,
  SidebarActionButton,
} from './graph/NodeActionSidebar';
import { useEditableGraphSelection } from './graph/useEditableGraphSelection';

/**
 * Cytoscape-driven dependency editor (UI #5 per v2-roadmap §Phase 11).
 *
 * - Top-level comps only — deps are top-level-only in the model.
 * - Tap source → candidate targets light up (all other comps
 *   that wouldn't close a cycle). Tap target → edge stages in
 *   the sidebar with "Queue add".
 * - Tap an existing dep edge → sidebar shows "Queue remove".
 * - Cycle detection is client-side via ``reachableSets`` so the
 *   invalid targets render as dashed-red before the user taps.
 *   The backend still enforces via ``would_create_cycle`` when
 *   the instruction applies; the UI predicate just prevents the
 *   user from queuing a dep that's already doomed.
 */

interface Props {
  projectId: string;
  topLevelComps: StructureNode[];
  depEdges: StructureEdge[];
}

export function DependencyGraphView({ projectId, topLevelComps, depEdges }: Props) {
  const enqueue = useEnqueueInstructionMutation(projectId);
  const compById = useMemo(() => {
    const m = new Map<string, StructureNode>();
    for (const c of topLevelComps) m.set(c.id, c);
    return m;
  }, [topLevelComps]);

  const elements = useMemo<ElementDefinition[]>(() => {
    const nodeEls = topLevelComps.map((c) => ({
      data: {
        id: c.id,
        name: c.name,
        type: c.kind === 'presentational' ? 'comp-top-pres' : 'comp-top',
      },
    }));
    const edgeEls = depEdges.map((e) => ({
      data: {
        id: e.id,
        source: e.source_id,
        target: e.target_id,
        type: 'dep',
      },
    }));
    return [...nodeEls, ...edgeEls];
  }, [topLevelComps, depEdges]);

  const existingEdgeKey = useCallback(
    (src: string, tgt: string) =>
      depEdges.some((e) => e.source_id === src && e.target_id === tgt),
    [depEdges],
  );

  // A target is invalid when it's the source itself, already
  // connected from the source, or in the source's upstream closure
  // (which means source → target would close a cycle).
  const invalidTargets = useCallback(
    (sourceId: string) => {
      const sets = reachableSets(elements, sourceId);
      const out = new Set<string>();
      for (const n of topLevelComps) {
        if (n.id === sourceId) continue;
        if (existingEdgeKey(sourceId, n.id)) {
          out.add(n.id);
          continue;
        }
        // sets.up are nodes that can reach `sourceId`. Adding
        // source → target where target is already upstream of
        // source closes a cycle.
        if (sets.up.has(n.id)) out.add(n.id);
      }
      return out;
    },
    [elements, topLevelComps, existingEdgeKey],
  );

  const candidates = useCallback(
    (sourceId: string) => {
      const out = new Set<string>();
      const invalid = invalidTargets(sourceId);
      for (const n of topLevelComps) {
        if (n.id === sourceId) continue;
        if (invalid.has(n.id)) continue;
        out.add(n.id);
      }
      return out;
    },
    [topLevelComps, invalidTargets],
  );

  const canConnect = useCallback(
    (sourceId: string, targetId: string) => candidates(sourceId).has(targetId),
    [candidates],
  );

  const selection = useEditableGraphSelection({ canConnect });

  const stylesheet = useMemo(
    () => [...fullDagStylesheet, ...editStylesheet],
    [],
  );

  const sidebar = (() => {
    const state = selection.state;
    if (state.kind === 'idle') return null;
    if (state.kind === 'source-selected') {
      const src = compById.get(state.sourceId);
      if (!src) return null;
      return (
        <NodeActionSidebar
          title={src.name}
          subtitle="Source — pick a target to add a dependency"
          onCancel={selection.cancel}
          actions={
            <p className="text-xs text-gray-400">
              Tap a candidate (dashed green border) to stage an edge. Blocked
              targets (dashed red) would close a cycle or already exist.
            </p>
          }
        />
      );
    }
    if (state.kind === 'edge-staged') {
      const src = compById.get(state.sourceId);
      const tgt = compById.get(state.targetId);
      if (!src || !tgt) return null;
      return (
        <NodeActionSidebar
          title={`${src.name} → ${tgt.name}`}
          subtitle="New dependency"
          onCancel={selection.cancel}
          actions={
            <SidebarActionButton
              label={enqueue.isPending ? 'Queuing…' : 'Queue add'}
              variant="primary"
              disabled={enqueue.isPending}
              testId="dep-graph-queue-add"
              onClick={() => {
                const ins: Instruction = {
                  instruction_type: 'AddDependency',
                  source_id: src.id,
                  source_name: src.name,
                  target_id: tgt.id,
                  target_name: tgt.name,
                };
                enqueue.mutate(ins, { onSuccess: selection.commit });
              }}
            />
          }
        />
      );
    }
    if (state.kind === 'edge-tapped') {
      const edge = depEdges.find((e) => e.id === state.edgeId);
      if (!edge) return null;
      const src = compById.get(edge.source_id);
      const tgt = compById.get(edge.target_id);
      if (!src || !tgt) return null;
      return (
        <NodeActionSidebar
          title={`${src.name} → ${tgt.name}`}
          subtitle="Existing dependency"
          onCancel={selection.cancel}
          actions={
            <SidebarActionButton
              label={enqueue.isPending ? 'Queuing…' : 'Queue remove'}
              variant="destructive"
              disabled={enqueue.isPending}
              testId="dep-graph-queue-remove"
              onClick={() => {
                enqueue.mutate(
                  {
                    instruction_type: 'RemoveDependency',
                    source_id: src.id,
                    source_name: src.name,
                    target_id: tgt.id,
                    target_name: tgt.name,
                  },
                  { onSuccess: selection.commit },
                );
              }}
            />
          }
        />
      );
    }
    return null;
  })();

  return (
    <div className="flex h-full min-h-[500px]" data-testid="dependency-graph-view">
      <div className="flex-1 min-w-0 min-h-0">
        <EditableGraph
          elements={elements}
          stylesheet={stylesheet}
          selection={selection}
          candidates={candidates}
          invalidTargets={invalidTargets}
          layout={{
            name: 'elk',
            elk: {
              algorithm: 'layered',
              'elk.direction': 'RIGHT',
              'elk.spacing.nodeNode': 40,
              'elk.layered.spacing.nodeNodeBetweenLayers': 80,
              'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
            },
            nodeDimensionsIncludeLabels: true,
            fit: true,
            padding: 40,
            animate: false,
          }}
          layoutKey={`${topLevelComps.length}-${depEdges.length}`}
        />
      </div>
      {sidebar}
    </div>
  );
}
