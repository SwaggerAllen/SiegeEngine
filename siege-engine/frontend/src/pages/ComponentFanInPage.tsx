import { Link, useParams } from 'react-router-dom';
import { FanInPanel } from '../components/FanInPanel';
import { useComparch } from '../hooks/queries/useComparchQueries';
import { useProject } from '../hooks/queries/useProjectQueries';
import { describeApiError } from '../lib/describeApiError';

/**
 * Full-page route for a fanned-out domain component's fan-in
 * synthesis. URL: ``/projects/:id/components/:compId/fanin``.
 *
 * Fan-in nodes only exist for fanned-out domain comps — a 404
 * from the API means the targeted comp is presentational or
 * un-fanned-out. The panel itself renders a clear message in
 * that case; we don't need a separate error screen here beyond
 * the project-level failure path.
 */
export function ComponentFanInPage() {
  const { id: projectId, compId } = useParams<{ id: string; compId: string }>();
  if (!projectId || !compId) return null;
  return <ComponentFanInShell projectId={projectId} compId={compId} />;
}

function ComponentFanInShell({
  projectId,
  compId,
}: {
  projectId: string;
  compId: string;
}) {
  const { data: project, error: projectError } = useProject(projectId);
  const { data: comparch } = useComparch(projectId, compId);

  if (projectError) {
    return (
      <div className="fixed inset-0 bg-gray-900 z-50 flex items-center justify-center text-white">
        <div className="text-center max-w-xl px-6">
          <h1 className="text-xl font-bold text-red-400 mb-2">
            Failed to load project
          </h1>
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

  const compName = comparch?.node.name || compId;

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
            <span className="text-gray-500 font-normal">
              /{' '}
              <Link
                to={`/projects/${projectId}/components/${compId}/comparch`}
                className="hover:text-white"
              >
                {compName}
              </Link>{' '}
              / Fan-in Synthesis
            </span>
          </h1>
        </div>
        <Link
          to={`/projects/${projectId}/components/${compId}/comparch`}
          className="text-sm text-gray-400 hover:text-white"
        >
          ← Architecture Doc
        </Link>
      </header>
      <main className="flex-1 overflow-auto">
        <FanInPanel
          projectId={projectId}
          compId={compId}
          ownerName={compName}
        />
      </main>
    </div>
  );
}
