import { useEffect, useMemo, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { BootstrapSubtabs } from '../components/BootstrapSubtabs';
import { ComponentList } from '../components/ComponentList';
import { DashboardMenu } from '../components/DashboardMenu';
import { FeatureExpansionPanel } from '../components/FeatureExpansionPanel';
import { FeatureList } from '../components/FeatureList';
import { PolicyList } from '../components/PolicyList';
import { RequirementsPanel } from '../components/RequirementsPanel';
import { ResponsibilityList } from '../components/ResponsibilityList';
import { SysarchPanel } from '../components/SysarchPanel';
import { VocabularyList } from '../components/VocabularyList';
import { useExpansion } from '../hooks/queries/useExpansionQueries';
import { useFeatures } from '../hooks/queries/useFeatureQueries';
import { useProject } from '../hooks/queries/useProjectQueries';
import { useResponsibilities } from '../hooks/queries/useRequirementsQueries';
import { debugLog } from '../lib/debugLog';
import { describeApiError } from '../lib/describeApiError';

type DashboardTab = 'expansion' | 'vocabulary' | 'requirements' | 'architecture';

function EmptySubtabMessage({ children }: { children: React.ReactNode }) {
  return <p className="p-6 text-sm italic text-gray-500">{children}</p>;
}

interface TabSpec {
  key: DashboardTab;
  label: string;
  enabled: boolean;
  /** When set, the tab's gate is blocked until the message clears.
   *  Shown as a tooltip on the disabled tab button. */
  disabledReason?: string;
}

export function ProjectDashboardLayout() {
  const { id: projectId } = useParams<{ id: string }>();
  if (!projectId) return null;
  return <DashboardShell projectId={projectId} />;
}

function DashboardShell({ projectId }: { projectId: string }) {
  const { data: currentProject, error: projectError } = useProject(projectId);

  // Gate queries: same as before, each panel still polls its own
  // state independently. We only read the approval + mint status
  // here to decide which tabs are enabled and which tab should be
  // the default landing spot.
  const { data: expansion } = useExpansion(projectId);
  const isExpansionApproved = !!expansion?.node.content;
  const { data: features } = useFeatures(projectId, isExpansionApproved);
  const featuresMinted = (features?.features.length ?? 0) > 0;
  const { data: responsibilities } = useResponsibilities(projectId, featuresMinted);
  const respsMinted = (responsibilities?.responsibilities.length ?? 0) > 0;

  const tabs: TabSpec[] = useMemo(
    () => [
      {
        key: 'expansion',
        label: 'Expansion',
        enabled: true,
      },
      {
        // Vocabulary is always enabled so users can pre-seed
        // project-level terms before expansion runs, and so the
        // terms minted from the expansion's <vocabulary> block
        // are visible in-flow without leaving the dashboard.
        // It is not part of the default-tab progression — the
        // phase-gated tabs (expansion → requirements →
        // architecture) remain the "where am I in the flow"
        // narrative and vocabulary is auxiliary.
        key: 'vocabulary',
        label: 'Vocabulary',
        enabled: true,
      },
      {
        key: 'requirements',
        label: 'Requirements',
        enabled: featuresMinted,
        disabledReason: featuresMinted
          ? undefined
          : 'Approve the feature expansion first — requirements unlocks once features are minted.',
      },
      {
        key: 'architecture',
        label: 'Architecture',
        enabled: respsMinted,
        disabledReason: respsMinted
          ? undefined
          : 'Approve the requirements first — the system architecture unlocks once top-level responsibilities are minted.',
      },
    ],
    [featuresMinted, respsMinted]
  );

  // Default tab: the furthest-along enabled tab. "Furthest along"
  // matches the user's mental model of "take me to the thing I'm
  // most likely reviewing right now" — if sysarch is unlocked
  // they're probably reviewing it, not going back to expansion.
  const defaultTab: DashboardTab = respsMinted
    ? 'architecture'
    : featuresMinted
      ? 'requirements'
      : 'expansion';

  const [activeTab, setActiveTab] = useState<DashboardTab>(defaultTab);

  // If a new tab becomes enabled while we're looking at an older
  // one, don't auto-jump — the user might still be reviewing.
  // But if we're on a tab that becomes disabled (shouldn't happen
  // outside of explicit data clears, but defensively), fall back.
  useEffect(() => {
    const current = tabs.find((t) => t.key === activeTab);
    if (current && !current.enabled) {
      setActiveTab(defaultTab);
    }
    // We intentionally do NOT auto-advance to new tabs as they
    // unlock — that would pull the user away mid-review.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabs.map((t) => t.enabled).join(',')]);

  useEffect(() => {
    debugLog('DashboardLayout.lifecycle', `MOUNT projectId=${projectId}`);
    return () => {
      debugLog('DashboardLayout.lifecycle', `UNMOUNT projectId=${projectId}`);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (projectError) {
    return (
      <div className="fixed inset-0 bg-gray-900 z-50 flex items-center justify-center text-white">
        <div className="text-center max-w-xl px-6">
          <h1 className="text-xl font-bold text-red-400 mb-2">Failed to load project</h1>
          <p className="text-gray-400 text-sm">
            {describeApiError(projectError, 'Unknown error')}
          </p>
          <Link
            to="/projects"
            className="mt-4 inline-block px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm"
          >
            Back to Projects
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-gray-900 text-white">
      <header className="border-b border-gray-700 px-3 py-2 flex items-center gap-3 shrink-0">
        <Link to="/projects" className="text-sm text-gray-400 hover:text-white">
          ← Projects
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-sm font-bold truncate">{currentProject?.name || 'Loading...'}</h1>
        </div>
        <DashboardMenu projectId={projectId} />
      </header>
      <nav
        className="border-b border-gray-700 px-3 flex items-center gap-1 shrink-0 overflow-x-auto"
        role="tablist"
        aria-label="Project dashboard tabs"
      >
        {tabs.map((tab) => {
          const isActive = tab.key === activeTab;
          const baseClasses =
            'px-4 py-2 text-sm border-b-2 -mb-px transition-colors shrink-0 whitespace-nowrap';
          const activeClasses = 'border-blue-500 text-white';
          const enabledClasses =
            'border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-600 cursor-pointer';
          const disabledClasses =
            'border-transparent text-gray-600 cursor-not-allowed';
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-controls={`tabpanel-${tab.key}`}
              disabled={!tab.enabled}
              title={tab.disabledReason}
              onClick={() => tab.enabled && setActiveTab(tab.key)}
              className={
                isActive
                  ? `${baseClasses} ${activeClasses}`
                  : tab.enabled
                    ? `${baseClasses} ${enabledClasses}`
                    : `${baseClasses} ${disabledClasses}`
              }
            >
              {tab.label}
            </button>
          );
        })}
      </nav>
      <main className="flex-1 overflow-hidden">
        {activeTab === 'expansion' && (
          <div
            role="tabpanel"
            id="tabpanel-expansion"
            aria-labelledby="tab-expansion"
            className="h-full"
          >
            <BootstrapSubtabs
              idPrefix="expansion"
              nodesLabel="Features"
              document={<FeatureExpansionPanel projectId={projectId} />}
              nodes={
                isExpansionApproved ? (
                  <FeatureList projectId={projectId} mintPending={isExpansionApproved} />
                ) : (
                  <EmptySubtabMessage>
                    Features appear here once the expansion is approved and minted.
                  </EmptySubtabMessage>
                )
              }
            />
          </div>
        )}
        {activeTab === 'vocabulary' && (
          <div
            role="tabpanel"
            id="tabpanel-vocabulary"
            aria-labelledby="tab-vocabulary"
            className="h-full"
          >
            {/* VocabularyList owns its own split-pane scrolling so
                this wrapper intentionally does NOT set overflow-auto —
                doing so would produce a double-scroll. */}
            <VocabularyList projectId={projectId} />
          </div>
        )}
        {activeTab === 'requirements' && (
          <div
            role="tabpanel"
            id="tabpanel-requirements"
            aria-labelledby="tab-requirements"
            className="h-full"
          >
            <BootstrapSubtabs
              idPrefix="requirements"
              nodesLabel="Responsibilities"
              document={<RequirementsPanel projectId={projectId} />}
              nodes={
                respsMinted ? (
                  <ResponsibilityList projectId={projectId} mintPending={featuresMinted} />
                ) : (
                  <EmptySubtabMessage>
                    Responsibilities appear here once the requirements draft is approved and minted.
                  </EmptySubtabMessage>
                )
              }
            />
          </div>
        )}
        {activeTab === 'architecture' && (
          <div
            role="tabpanel"
            id="tabpanel-architecture"
            aria-labelledby="tab-architecture"
            className="h-full"
          >
            <BootstrapSubtabs
              idPrefix="architecture"
              nodesLabel="Components & policies"
              document={<SysarchPanel projectId={projectId} />}
              nodes={
                respsMinted ? (
                  <div className="space-y-0">
                    <ComponentList projectId={projectId} mintPending={respsMinted} />
                    <PolicyList projectId={projectId} mintPending={respsMinted} />
                  </div>
                ) : (
                  <EmptySubtabMessage>
                    Components and policies appear here once the system architecture is approved and minted.
                  </EmptySubtabMessage>
                )
              }
            />
          </div>
        )}
      </main>
    </div>
  );
}
