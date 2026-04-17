import { Link, useParams } from 'react-router-dom';
import { ImplPanel } from '../components/ImplPanel';
import { useComparch } from '../hooks/queries/useComparchQueries';
import { useImplSub } from '../hooks/queries/useImplQueries';
import { useProject } from '../hooks/queries/useProjectQueries';
import { useSubcomparch } from '../hooks/queries/useSubcomparchQueries';
import { describeApiError } from '../lib/describeApiError';

/**
 * Full-page route for a single subcomponent's implementation.
 * URL: ``/projects/:id/components/:compId/subcomponents/:subId/impl``.
 *
 * The impl shell is minted by comparch_mint at subcomponent
 * creation time and filled by generate_impl post-subcomparch
 * approval. Layout mirrors SubcomponentComparchPage for
 * consistency.
 */
export function SubcomponentImplPage() {
  const { id: projectId, compId, subId } = useParams<{
    id: string;
    compId: string;
    subId: string;
  }>();
  if (!projectId || !compId || !subId) return null;
  return (
    <SubcomponentImplShell
      projectId={projectId}
      compId={compId}
      subId={subId}
    />
  );
}

function SubcomponentImplShell({
  projectId,
  compId,
  subId,
}: {
  projectId: string;
  compId: string;
  subId: string;
}) {
  const { data: project, error: projectError } = useProject(projectId);
  const { data: parentComparch } = useComparch(projectId, compId);
  const { data: subcomparch } = useSubcomparch(projectId, compId, subId);
  const { error: implError } = useImplSub(projectId, compId, subId);

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
          <Link
            to={`/projects/${projectId}/components/${compId}/subcomponents/${subId}/subcomparch`}
            className="mt-4 inline-block px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm"
          >
            Back to Subcomponent Arch Doc
          </Link>
        </div>
      </div>
    );
  }

  const parentName = parentComparch?.node.name || compId;
  const subName = subcomparch?.node.name || subId;

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
                {parentName}
              </Link>{' '}
              /{' '}
              <Link
                to={`/projects/${projectId}/components/${compId}/subcomponents/${subId}/subcomparch`}
                className="hover:text-white"
              >
                {subName}
              </Link>{' '}
              / Implementation
            </span>
          </h1>
        </div>
        <Link
          to={`/projects/${projectId}/components/${compId}/subcomponents/${subId}/subcomparch`}
          className="text-sm text-gray-400 hover:text-white"
        >
          ← Subcomponent Arch Doc
        </Link>
      </header>
      <main className="flex-1 overflow-auto">
        <ImplPanel
          kind="sub"
          projectId={projectId}
          parentCompId={compId}
          subId={subId}
          ownerName={subName}
        />
      </main>
    </div>
  );
}
