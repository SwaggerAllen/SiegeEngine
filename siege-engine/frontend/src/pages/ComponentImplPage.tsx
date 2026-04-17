import { Link, useParams } from 'react-router-dom';
import { ImplPanel } from '../components/ImplPanel';
import { useComparch } from '../hooks/queries/useComparchQueries';
import { useImplTopLevel } from '../hooks/queries/useImplQueries';
import { useProject } from '../hooks/queries/useProjectQueries';
import { describeApiError } from '../lib/describeApiError';

/**
 * Full-page route for an un-fanned-out top-level component's
 * implementation. URL: ``/projects/:id/components/:compId/impl``.
 *
 * Only un-fanned-out comps get a top-level impl — fanned-out
 * comps have no impl of their own (their impl lives in their
 * subcomponents' impls). The impl shell is minted by
 * comparch_mint when the comparch has no subcomponents; if the
 * URL is hit for a fanned-out comp, the impl fetch returns 404.
 */
export function ComponentImplPage() {
  const { id: projectId, compId } = useParams<{ id: string; compId: string }>();
  if (!projectId || !compId) return null;
  return <ComponentImplShell projectId={projectId} compId={compId} />;
}

function ComponentImplShell({
  projectId,
  compId,
}: {
  projectId: string;
  compId: string;
}) {
  const { data: project, error: projectError } = useProject(projectId);
  const { data: comparch } = useComparch(projectId, compId);
  const { error: implError } = useImplTopLevel(projectId, compId);

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

  if (implError) {
    return (
      <div className="fixed inset-0 bg-gray-900 z-50 flex items-center justify-center text-white">
        <div className="text-center max-w-xl px-6">
          <h1 className="text-xl font-bold text-red-400 mb-2">
            Failed to load implementation
          </h1>
          <p className="text-gray-400 text-sm">
            {describeApiError(implError, 'Unknown error')}
          </p>
          <p className="text-gray-500 text-xs mt-2">
            Top-level impls only exist for un-fanned-out components
            (no subcomponents). If this component has subcomponents,
            visit the subcomponent's impl page instead.
          </p>
          <Link
            to={`/projects/${projectId}/components/${compId}/comparch`}
            className="mt-4 inline-block px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm"
          >
            Back to Architecture Doc
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
              / Implementation
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
        <ImplPanel
          kind="top-level"
          projectId={projectId}
          compId={compId}
          ownerName={compName}
        />
      </main>
    </div>
  );
}
