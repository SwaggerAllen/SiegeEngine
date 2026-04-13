import { useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ComponentList } from '../components/ComponentList';
import { DashboardMenu } from '../components/DashboardMenu';
import { FeatureExpansionPanel } from '../components/FeatureExpansionPanel';
import { FeatureList } from '../components/FeatureList';
import { PolicyList } from '../components/PolicyList';
import { RequirementsPanel } from '../components/RequirementsPanel';
import { ResponsibilityList } from '../components/ResponsibilityList';
import { SysarchPanel } from '../components/SysarchPanel';
import { useExpansion } from '../hooks/queries/useExpansionQueries';
import { useFeatures } from '../hooks/queries/useFeatureQueries';
import { useProject } from '../hooks/queries/useProjectQueries';
import { useResponsibilities } from '../hooks/queries/useRequirementsQueries';
import { debugLog } from '../lib/debugLog';
import { describeApiError } from '../lib/describeApiError';

export function ProjectDashboardLayout() {
  const { id: projectId } = useParams<{ id: string }>();
  if (!projectId) return null;
  return <DashboardShell projectId={projectId} />;
}

function DashboardShell({ projectId }: { projectId: string }) {
  const { data: currentProject, error: projectError } = useProject(projectId);
  // The dashboard reads a few bootstrap queries to decide which
  // panels to render. Each panel manages its own polling when the
  // corresponding mint might still be running.
  const { data: expansion } = useExpansion(projectId);
  const isExpansionApproved = !!expansion?.node.content;
  // Requirements panel shows up once features are minted — that's
  // when the reqs node gets bootstrapped and its first generation
  // job is enqueued.
  const { data: features } = useFeatures(projectId, isExpansionApproved);
  const featuresMinted = (features?.features.length ?? 0) > 0;
  // Sysarch panel shows up once top-level resps are minted.
  const { data: responsibilities } = useResponsibilities(projectId, featuresMinted);
  const respsMinted = (responsibilities?.responsibilities.length ?? 0) > 0;

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
      <main className="flex-1 overflow-auto">
        <FeatureExpansionPanel projectId={projectId} />
        {isExpansionApproved && (
          <FeatureList projectId={projectId} mintPending={isExpansionApproved} />
        )}
        {featuresMinted && (
          <>
            <RequirementsPanel projectId={projectId} />
            <ResponsibilityList projectId={projectId} mintPending={featuresMinted} />
          </>
        )}
        {respsMinted && (
          <>
            <SysarchPanel projectId={projectId} />
            <ComponentList projectId={projectId} mintPending={respsMinted} />
            <PolicyList projectId={projectId} mintPending={respsMinted} />
          </>
        )}
      </main>
    </div>
  );
}
