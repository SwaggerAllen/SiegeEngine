import { useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { FeatureExpansionPanel } from '../components/FeatureExpansionPanel';
import { FeatureList } from '../components/FeatureList';
import { useExpansion } from '../hooks/queries/useExpansionQueries';
import { useProject } from '../hooks/queries/useProjectQueries';
import { debugLog } from '../lib/debugLog';
import { describeApiError } from '../lib/describeApiError';

export function ProjectDashboardLayout() {
  const { id: projectId } = useParams<{ id: string }>();
  if (!projectId) return null;
  return <DashboardShell projectId={projectId} />;
}

function DashboardShell({ projectId }: { projectId: string }) {
  const { data: currentProject, error: projectError } = useProject(projectId);
  // The dashboard reads the expansion once to decide whether to
  // render the FeatureList at all. The FeatureList manages its
  // own polling when the mint might still be running.
  const { data: expansion } = useExpansion(projectId);
  const isExpansionApproved = !!expansion?.node.content;

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
      </header>
      <main className="flex-1 overflow-auto">
        <FeatureExpansionPanel projectId={projectId} />
        {isExpansionApproved && (
          <FeatureList projectId={projectId} mintPending={isExpansionApproved} />
        )}
      </main>
    </div>
  );
}
