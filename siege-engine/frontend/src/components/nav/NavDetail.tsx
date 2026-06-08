import { lazy, Suspense } from 'react';
import type { StructureNode } from '../../api/structure';
import { ComparchPanel } from '../ComparchPanel';
import { ComponentOverviewPanel } from '../ComponentOverviewPanel';
import { FanInPanel } from '../FanInPanel';
import { FeatureExpansionPanel } from '../FeatureExpansionPanel';

// Phase 10's DAG view pulls in elkjs (~1.5MB minified). Keep it
// out of the initial bundle by code-splitting both DAG entry
// points — the chunk only loads when the user picks the
// Decomposition Graph sidebar entry or opens a comp's
// Decomposition tab.
const FullDagView = lazy(() =>
  import('../graph/FullDagView').then((m) => ({ default: m.FullDagView })),
);
const ComponentDecompositionPanel = lazy(() =>
  import('../graph/ComponentDecompositionPanel').then((m) => ({
    default: m.ComponentDecompositionPanel,
  })),
);
import { DebugPanel } from '../DebugPanel';
import { ImplPanel } from '../ImplPanel';
import { CohortsPanel } from '../CohortsPanel';
import { TierOpsPanel } from '../TierOpsPanel';
import { ReferencesList } from '../ReferencesList';
import { RequirementsPanel } from '../RequirementsPanel';
import { SubcomparchPanel } from '../SubcomparchPanel';
import { SubstrateOverviewPanel } from '../SubstrateOverviewPanel';
import { SysarchPanel } from '../SysarchPanel';
import { V3BodyPanel } from '../V3BodyPanel';
import { VocabularyList } from '../VocabularyList';
import { useProject } from '../../hooks/queries/useProjectQueries';
import { SYNTHETIC_IDS } from './buildNavTree';

interface Props {
  projectId: string;
  selectedId: string | null;
  /** Flat node list from the nav-tree query, used to resolve
   *  metadata (name, parent_id) for the selected id. */
  nodes: StructureNode[];
  /** ``?view=`` URL param. When a top-level comp is selected this
   *  chooses between Overview (default / ``overview``), Comparch
   *  (``comparch``), and Decomposition (``decomposition``).
   *  Ignored for other tiers. */
  view: string | null;
}

/**
 * Dispatches the selected tree node to the appropriate detail
 * panel. The workspace layout provides the left sidebar; this is
 * the right pane.
 *
 * Every existing per-tier panel (ComparchPanel, ImplPanel, etc.)
 * is reused as-is — they were already standalone components, the
 * previous full-page "shells" just wrapped them with a header.
 * The workspace header replaces those shells.
 */
export function NavDetail({ projectId, selectedId, nodes, view }: Props) {
  const { data: project } = useProject(projectId);
  const isUpload = project?.source === 'upload';
  if (!selectedId) {
    return <EmptyState />;
  }

  // Synthetic views — no backing node.
  if (selectedId === SYNTHETIC_IDS.VOCABULARY) {
    return (
      <div className="h-full overflow-hidden">
        <VocabularyList projectId={projectId} />
      </div>
    );
  }
  if (selectedId === SYNTHETIC_IDS.REFERENCES) {
    return (
      <div className="h-full overflow-hidden">
        <ReferencesList projectId={projectId} />
      </div>
    );
  }
  if (selectedId === SYNTHETIC_IDS.DAG) {
    return (
      <div className="h-full w-full">
        <Suspense
          fallback={
            <div className="p-6 text-sm text-gray-400">Loading graph…</div>
          }
        >
          <FullDagView projectId={projectId} />
        </Suspense>
      </div>
    );
  }
  if (
    selectedId === SYNTHETIC_IDS.QUEUE ||
    selectedId === SYNTHETIC_IDS.GEN_QUEUE
  ) {
    // Phase 3 migration: the pending-change queue and the
    // generation-job queue were dashboard surfaces over the old
    // backend's write pipeline. With writes moving to Claude Code
    // skills, neither queue exists in the new architecture. Sidebar
    // entries kept for now as no-op landing pages; the synthetic
    // IDs themselves will fall out in Phase 4.
    return <QueueRetired />;
  }
  if (selectedId === SYNTHETIC_IDS.TIER_OPS) {
    return (
      <div className="h-full overflow-auto">
        <TierOpsPanel projectId={projectId} />
      </div>
    );
  }
  if (selectedId === SYNTHETIC_IDS.COHORTS) {
    return (
      <div className="h-full overflow-auto">
        <CohortsPanel projectId={projectId} />
      </div>
    );
  }
  if (selectedId === SYNTHETIC_IDS.DEBUG) {
    return (
      <div className="h-full overflow-auto">
        <DebugPanel projectId={projectId} />
      </div>
    );
  }
  if (
    selectedId === SYNTHETIC_IDS.FEATURE_EXPANSION ||
    selectedId === SYNTHETIC_IDS.REQUIREMENTS ||
    selectedId === SYNTHETIC_IDS.SYSARCH
  ) {
    // Upload-imported projects: synthetic substrate-root entries.
    // The rich editor panels (FeatureExpansionPanel / etc.) need a
    // backing legacy node + its tier endpoints, neither of which
    // exist here — render the read-only per-item overview instead.
    return (
      <SubstrateOverviewPanel
        projectId={projectId}
        substrateId={selectedId}
        nodes={nodes}
      />
    );
  }

  const node = nodes.find((n) => n.id === selectedId) ?? null;
  if (!node) {
    return <MissingNode />;
  }

  switch (node.tier) {
    case 'expansion':
      return (
        <div className="h-full overflow-auto">
          <FeatureExpansionPanel projectId={projectId} />
        </div>
      );
    case 'reqs':
      return (
        <div className="h-full overflow-auto">
          <RequirementsPanel projectId={projectId} />
        </div>
      );
    case 'sysarch':
      return (
        <div className="h-full overflow-auto">
          <SysarchPanel projectId={projectId} />
        </div>
      );
    case 'comp': {
      if (node.parent_id === null) {
        // Top-level component — Overview is the default tab, users
        // flip to Comparch via ``?view=comparch`` or to the
        // decomposition graph via ``?view=decomposition``. Fan-in
        // and Impl tabs navigate to their own child nodes, so they
        // don't land here.
        if (view === 'comparch') {
          // Upload projects don't have legacy SQL rows for comparch
          // drafts — fall back to the raw substrate body so the user
          // can read what's on disk instead of staring at a 404.
          if (isUpload) {
            return (
              <V3BodyPanel
                projectId={projectId}
                scope={{ tier: 'comparch', comp_id: node.id }}
                title={`${node.name} — Comparch`}
                hint="Raw comparch artifact from the imported substrate."
              />
            );
          }
          return (
            <div className="h-full overflow-auto">
              <ComparchPanel
                projectId={projectId}
                componentId={node.id}
                componentName={node.name}
              />
            </div>
          );
        }
        if (view === 'decomposition') {
          return (
            <div className="h-full w-full">
              <Suspense
                fallback={
                  <div className="p-6 text-sm text-gray-400">
                    Loading graph…
                  </div>
                }
              >
                <ComponentDecompositionPanel
                  projectId={projectId}
                  componentId={node.id}
                />
              </Suspense>
            </div>
          );
        }
        return <ComponentOverviewPanel projectId={projectId} component={node} />;
      }
      // Subcomponent → subcomparch panel. Upload projects don't have
      // the legacy SQL row, so fall back to the substrate body.
      if (isUpload) {
        return (
          <V3BodyPanel
            projectId={projectId}
            scope={{
              tier: 'subcomparch',
              parent_id: node.parent_id,
              sub_id: node.id,
            }}
            title={`${node.name} — Subcomparch`}
            hint="Raw subcomparch artifact from the imported substrate."
          />
        );
      }
      return (
        <div className="h-full overflow-auto">
          <SubcomparchPanel
            projectId={projectId}
            parentCompId={node.parent_id}
            subId={node.id}
            subName={node.name}
          />
        </div>
      );
    }
    case 'fanin': {
      if (!node.parent_id) return <MissingParent />;
      const owner = nodes.find((n) => n.id === node.parent_id);
      return (
        <div className="h-full overflow-auto">
          <FanInPanel
            projectId={projectId}
            compId={node.parent_id}
            ownerName={owner?.name ?? node.parent_id}
          />
        </div>
      );
    }
    case 'impl': {
      // Impl's parent is either a top-level comp (un-fanned-out)
      // or a subcomponent. ImplPanel handles both via its
      // discriminated ``kind`` union.
      if (!node.parent_id) return <MissingParent />;
      const owner = nodes.find((n) => n.id === node.parent_id);
      const ownerName = owner?.name ?? node.parent_id;
      if (owner && owner.tier === 'comp' && owner.parent_id === null) {
        // Un-fanned-out top-level impl.
        return (
          <div className="h-full overflow-auto">
            <ImplPanel
              kind="top-level"
              projectId={projectId}
              compId={node.parent_id}
              ownerName={ownerName}
            />
          </div>
        );
      }
      // Subcomponent impl.
      const parentCompId = owner?.parent_id ?? '';
      return (
        <div className="h-full overflow-auto">
          <ImplPanel
            kind="sub"
            projectId={projectId}
            parentCompId={parentCompId}
            subId={node.parent_id}
            ownerName={ownerName}
          />
        </div>
      );
    }
    case 'policy':
      // Policies live inline in the sysarch body — no per-node
      // substrate. Surface the node metadata + point the user at
      // the sysarch body for the full <policy> block.
      return <PolicyDetail node={node} projectId={projectId} />;
    default:
      return <UnknownTier tier={node.tier} />;
  }
}

function PolicyDetail({
  node,
  projectId,
}: {
  node: StructureNode;
  projectId: string;
}) {
  return (
    <div className="h-full overflow-auto p-6 space-y-3">
      <header>
        <h2 className="text-lg font-semibold text-gray-100">{node.name}</h2>
        <p className="font-mono text-[11px] text-gray-600 mt-1">{node.id}</p>
      </header>
      <p className="text-xs text-gray-400">
        Cross-cutting policy from the sysarch body. Each top-level component
        depends on it. The full ``&lt;policy&gt;`` block — trigger, rationale,
        and required responsibility — lives inline in the{' '}
        <a
          href={`/projects/${projectId}?node=${SYNTHETIC_IDS.SYSARCH}`}
          className="text-cyan-300 hover:text-cyan-200 underline"
        >
          sysarch body
        </a>
        .
      </p>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full flex items-center justify-center p-8 text-center">
      <div className="max-w-md">
        <h2 className="text-base font-semibold text-gray-200 mb-2">
          Select a node to view it
        </h2>
        <p className="text-sm text-gray-500">
          The sidebar is your map. Click any tier on the left to render its
          content here — draft reviews, XML documents, the decomposition graph.
          Ancestors auto-expand when you navigate via URL.
        </p>
      </div>
    </div>
  );
}

function MissingNode() {
  return (
    <div className="h-full flex items-center justify-center p-8 text-center">
      <p className="text-sm text-gray-500">
        Node not found in the current tree. It may have been deleted or not yet
        minted.
      </p>
    </div>
  );
}

function MissingParent() {
  return (
    <div className="h-full flex items-center justify-center p-8 text-center">
      <p className="text-sm text-red-400">
        Tree node is missing its parent reference — can't resolve the detail
        panel.
      </p>
    </div>
  );
}

function UnknownTier({ tier }: { tier: string }) {
  return (
    <div className="h-full flex items-center justify-center p-8 text-center">
      <p className="text-sm text-gray-500">
        No detail view for tier <code>{tier}</code> yet.
      </p>
    </div>
  );
}

function QueueRetired() {
  return (
    <div className="h-full flex items-center justify-center p-8 text-center max-w-md mx-auto">
      <div>
        <h2 className="text-sm font-semibold text-gray-300 mb-2">Queue retired</h2>
        <p className="text-sm text-gray-400">
          The pending-change queue and generation-job queue were part of the old
          write pipeline. Work now happens via Claude Code skills; there is no
          server-side queue to inspect from the dashboard.
        </p>
      </div>
    </div>
  );
}

