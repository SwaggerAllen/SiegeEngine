import { lazy, Suspense } from 'react';
import type { StructureNode } from '../../api/structure';
import { ComparchPanel } from '../ComparchPanel';
import { ComponentOverviewPanel } from '../ComponentOverviewPanel';
import { FanInPanel } from '../FanInPanel';
import { FeatureExpansionPanel } from '../FeatureExpansionPanel';

// Phase 10's DAG view pulls in elkjs (~1.5MB minified). Keep it
// out of the initial bundle by code-splitting on the import — the
// chunk only loads when the user selects the Decomposition Graph
// entry in the sidebar.
const FullDagView = lazy(() =>
  import('../graph/FullDagView').then((m) => ({ default: m.FullDagView })),
);
import { ImplPanel } from '../ImplPanel';
import { QueuePanel } from '../QueuePanel';
import { ReferencesList } from '../ReferencesList';
import { RequirementsPanel } from '../RequirementsPanel';
import { SubcomparchPanel } from '../SubcomparchPanel';
import { SubreqsPanel } from '../SubreqsPanel';
import { SysarchPanel } from '../SysarchPanel';
import { VocabularyList } from '../VocabularyList';
import { SYNTHETIC_IDS } from './buildNavTree';

interface Props {
  projectId: string;
  selectedId: string | null;
  /** Flat node list from the nav-tree query, used to resolve
   *  metadata (name, parent_id) for the selected id. */
  nodes: StructureNode[];
  /** ``?view=`` URL param. When a top-level comp is selected this
   *  chooses between Overview (default / ``overview``) and
   *  Comparch (``comparch``). Ignored for other tiers. */
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
  if (selectedId === SYNTHETIC_IDS.QUEUE) {
    return (
      <div className="h-full overflow-auto">
        <QueuePanel projectId={projectId} />
      </div>
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
    case 'subreqs': {
      // Subreqs node's parent_id is the owning comp.
      if (!node.parent_id) return <MissingParent />;
      const comp = nodes.find((n) => n.id === node.parent_id);
      // SubreqsPanel manages its own scroll container — it stacks
      // the responsibility coverage summary above the draft panel
      // and needs to control overflow so the two sections scroll
      // together. Drop our wrapper here so we don't double-scroll.
      return (
        <div className="h-full">
          <SubreqsPanel
            projectId={projectId}
            componentId={node.parent_id}
            componentName={comp?.name ?? node.parent_id}
          />
        </div>
      );
    }
    case 'comp': {
      if (node.parent_id === null) {
        // Top-level component — Overview is the default tab, users
        // flip to Comparch via ``?view=comparch``. Fan-in and Impl
        // tabs navigate to their own child nodes, so they don't
        // land here.
        if (view === 'comparch') {
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
        return <ComponentOverviewPanel component={node} />;
      }
      // Subcomponent → subcomparch panel.
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
    default:
      return <UnknownTier tier={node.tier} />;
  }
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
