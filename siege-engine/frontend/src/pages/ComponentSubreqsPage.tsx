import { Link, useParams } from 'react-router-dom';
import { SubreqsPanel } from '../components/SubreqsPanel';
import { SubresponsibilityList } from '../components/SubresponsibilityList';
import { useSubreqs } from '../hooks/queries/useSubreqsQueries';
import { useProject } from '../hooks/queries/useProjectQueries';
import { describeApiError } from '../lib/describeApiError';

/**
 * Full-page route for a single component's subrequirements.
 *
 * URL: ``/projects/:id/components/:compId/subreqs``
 *
 * Layout:
 * - Header with ← Back to dashboard link + project name +
 *   component name.
 * - SubreqsPanel (four-state draft review UI).
 * - SubresponsibilityList (polling while mint might be running).
 *
 * The component metadata (name, role, api-intent) comes from the
 * backend via the subreqs GET endpoint — we use the panel's
 * node.name as a fallback display name until the real component
 * lookup lands in a dedicated endpoint.
 */
export function ComponentSubreqsPage() {
  const { id: projectId, compId } = useParams<{ id: string; compId: string }>();
  if (!projectId || !compId) return null;
  return <ComponentSubreqsShell projectId={projectId} compId={compId} />;
}

function ComponentSubreqsShell({
  projectId,
  compId,
}: {
  projectId: string;
  compId: string;
}) {
  const { data: project, error: projectError } = useProject(projectId);
  const { data: subreqs } = useSubreqs(projectId, compId);
  const isApproved = !!subreqs?.node.content;

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
        <Link
          to={`/projects/${projectId}`}
          className="text-sm text-gray-400 hover:text-white"
        >
          ← Dashboard
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-sm font-bold truncate">
            {project?.name || 'Loading…'}{' '}
            <span className="text-gray-500 font-normal">/ Subrequirements</span>
          </h1>
        </div>
      </header>
      <main className="flex-1 overflow-auto">
        <SubreqsPanel
          projectId={projectId}
          componentId={compId}
          componentName={compId}
        />
        {isApproved && (
          <SubresponsibilityList
            projectId={projectId}
            componentId={compId}
            mintPending={isApproved}
          />
        )}
      </main>
    </div>
  );
}
