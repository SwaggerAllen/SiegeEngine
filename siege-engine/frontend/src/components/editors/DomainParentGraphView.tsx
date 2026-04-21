import { useCallback, useMemo } from 'react';
import type { ElementDefinition } from 'cytoscape';
import type { Instruction } from '../../api/queue';
import type { StructureNode, StructureEdge } from '../../api/structure';
import { useEnqueueInstructionMutation } from '../../hooks/mutations/useQueueMutations';
import { fullDagStylesheet } from '../graph/stylesheet';
import { EditableGraph } from './graph/EditableGraph';
import { editStylesheet } from './graph/editStylesheet';
import {
  NodeActionSidebar,
  SidebarActionButton,
} from './graph/NodeActionSidebar';
import { useEditableGraphSelection } from './graph/useEditableGraphSelection';

/**
 * Cytoscape-driven domain-parent editor (UI #6 per v2-roadmap §Phase 11).
 *
 * - Top-level comps only. Presentational and domain comps render
 *   with distinct styling (driven by the existing
 *   ``fullDagStylesheet`` type field).
 * - Tap a presentational comp → candidate targets are the domain
 *   comps. Tapping a domain comp while nothing's selected is a
 *   no-op (source must be presentational per spec rule).
 * - Client-side 1–2 parent cap: if the presentational source
 *   already has 2 domain-parent edges, block the third target
 *   as ``invalid-target``.
 * - Tap an existing edge → sidebar offers "Queue remove".
 */

const MAX_DOMAIN_PARENTS_PER_PRESENTATIONAL = 2;

interface Props {
  projectId: string;
  topLevelComps: StructureNode[];
  domainParentEdges: StructureEdge[];
}

export function DomainParentGraphView({
  projectId,
  topLevelComps,
  domainParentEdges,
}: Props) {
  const enqueue = useEnqueueInstructionMutation(projectId);
  const compById = useMemo(() => {
    const m = new Map<string, StructureNode>();
    for (const c of topLevelComps) m.set(c.id, c);
    return m;
  }, [topLevelComps]);

  const presentationalIds = useMemo(
    () => new Set(topLevelComps.filter((c) => c.kind === 'presentational').map((c) => c.id)),
    [topLevelComps],
  );
  const domainIds = useMemo(
    () => new Set(topLevelComps.filter((c) => c.kind === 'domain').map((c) => c.id)),
    [topLevelComps],
  );

  const elements = useMemo<ElementDefinition[]>(() => {
    const nodeEls = topLevelComps.map((c) => ({
      data: {
        id: c.id,
        name: c.name,
        type: c.kind === 'presentational' ? 'comp-top-pres' : 'comp-top',
      },
    }));
    const edgeEls = domainParentEdges.map((e) => ({
      data: {
        id: e.id,
        source: e.source_id,
        target: e.target_id,
        type: 'domain_parent',
      },
    }));
    return [...nodeEls, ...edgeEls];
  }, [topLevelComps, domainParentEdges]);

  const parentCountBySource = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of domainParentEdges) {
      m.set(e.source_id, (m.get(e.source_id) ?? 0) + 1);
    }
    return m;
  }, [domainParentEdges]);

  // Invalid targets for a presentational source:
  // - The source itself
  // - Any non-domain comp (presentational→presentational is invalid)
  // - Any domain comp already connected from this source
  // - Everything if the source has hit the 1-2 parent cap
  const invalidTargets = useCallback(
    (sourceId: string) => {
      const out = new Set<string>();
      // If source isn't presentational, every tap-target is invalid.
      // We also style domain comps as invalid so users see nothing
      // is clickable — effectively a no-op cancel.
      if (!presentationalIds.has(sourceId)) {
        for (const c of topLevelComps) {
          if (c.id !== sourceId) out.add(c.id);
        }
        return out;
      }
      const capped =
        (parentCountBySource.get(sourceId) ?? 0) >= MAX_DOMAIN_PARENTS_PER_PRESENTATIONAL;
      for (const c of topLevelComps) {
        if (c.id === sourceId) continue;
        // Presentational comps are never valid targets.
        if (c.kind !== 'domain') {
          out.add(c.id);
          continue;
        }
        if (
          domainParentEdges.some(
            (e) => e.source_id === sourceId && e.target_id === c.id,
          )
        ) {
          out.add(c.id);
          continue;
        }
        if (capped) out.add(c.id);
      }
      return out;
    },
    [topLevelComps, presentationalIds, parentCountBySource, domainParentEdges],
  );

  const candidates = useCallback(
    (sourceId: string) => {
      if (!presentationalIds.has(sourceId)) return new Set<string>();
      const invalid = invalidTargets(sourceId);
      const out = new Set<string>();
      for (const c of topLevelComps) {
        if (c.id === sourceId) continue;
        if (!domainIds.has(c.id)) continue;
        if (invalid.has(c.id)) continue;
        out.add(c.id);
      }
      return out;
    },
    [topLevelComps, presentationalIds, domainIds, invalidTargets],
  );

  const canConnect = useCallback(
    (src: string, tgt: string) => candidates(src).has(tgt),
    [candidates],
  );

  const selection = useEditableGraphSelection({ canConnect });

  const stylesheet = useMemo(() => [...fullDagStylesheet, ...editStylesheet], []);

  const sidebar = (() => {
    const state = selection.state;
    if (state.kind === 'idle') return null;
    if (state.kind === 'source-selected') {
      const src = compById.get(state.sourceId);
      if (!src) return null;
      if (!presentationalIds.has(src.id)) {
        return (
          <NodeActionSidebar
            title={src.name}
            subtitle="Domain component"
            onCancel={selection.cancel}
            actions={
              <p className="text-xs text-gray-400">
                Domain-parent edges originate from presentational components.
                Select a presentational comp to add one.
              </p>
            }
          />
        );
      }
      const used = parentCountBySource.get(src.id) ?? 0;
      const capped = used >= MAX_DOMAIN_PARENTS_PER_PRESENTATIONAL;
      return (
        <NodeActionSidebar
          title={src.name}
          subtitle={`Presentational — ${used}/${MAX_DOMAIN_PARENTS_PER_PRESENTATIONAL} domain parents`}
          onCancel={selection.cancel}
          actions={
            <p className="text-xs text-gray-400">
              {capped
                ? 'This presentational already has the maximum of 2 domain parents. Remove one before adding another.'
                : 'Tap a domain comp (dashed green) to add a domain-parent edge. Dashed red marks existing edges.'}
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
          title={`${src.name} presents ${tgt.name}`}
          subtitle="New domain-parent edge"
          onCancel={selection.cancel}
          actions={
            <SidebarActionButton
              label={enqueue.isPending ? 'Queuing…' : 'Queue add'}
              variant="primary"
              disabled={enqueue.isPending}
              testId="domain-parent-graph-queue-add"
              onClick={() => {
                const ins: Instruction = {
                  instruction_type: 'AddDomainParent',
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
      const edge = domainParentEdges.find((e) => e.id === state.edgeId);
      if (!edge) return null;
      const src = compById.get(edge.source_id);
      const tgt = compById.get(edge.target_id);
      if (!src || !tgt) return null;
      return (
        <NodeActionSidebar
          title={`${src.name} presents ${tgt.name}`}
          subtitle="Existing domain-parent edge"
          onCancel={selection.cancel}
          actions={
            <SidebarActionButton
              label={enqueue.isPending ? 'Queuing…' : 'Queue remove'}
              variant="destructive"
              disabled={enqueue.isPending}
              testId="domain-parent-graph-queue-remove"
              onClick={() => {
                enqueue.mutate(
                  {
                    instruction_type: 'RemoveDomainParent',
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
    <div
      className="flex h-full min-h-[500px]"
      data-testid="domain-parent-graph-view"
    >
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
              'elk.direction': 'DOWN',
              'elk.spacing.nodeNode': 40,
              'elk.layered.spacing.nodeNodeBetweenLayers': 80,
              'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
            },
            nodeDimensionsIncludeLabels: true,
            fit: true,
            padding: 40,
            animate: false,
          }}
          layoutKey={`${topLevelComps.length}-${domainParentEdges.length}`}
        />
      </div>
      {sidebar}
    </div>
  );
}
