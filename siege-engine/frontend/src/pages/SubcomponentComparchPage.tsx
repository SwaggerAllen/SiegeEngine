import { Link, useParams } from 'react-router-dom';
import { SubcomparchPanel } from '../components/SubcomparchPanel';
import { useComparch } from '../hooks/queries/useComparchQueries';
import { useSubcomparch } from '../hooks/queries/useSubcomparchQueries';
import { useProject } from '../hooks/queries/useProjectQueries';
import { describeApiError } from '../lib/describeApiError';

/**
 * Full-page route for a single subcomponent's architecture doc.
 * URL: ``/projects/:id/components/:compId/subcomponents/:subId/subcomparch``.
 *
 * Layout mirrors :file:`ComponentComparchPage.tsx`:
 * - Header with back link to dashboard, parent component's
 *   comparch page, and subcomponent name breadcrumb
 * - SubcomparchPanel (four-state draft review)
 */
export function SubcomponentComparchPage() {
  const { id: projectId, compId, subId } = useParams<{
    id: string;
    compId: string;
    subId: string;
  }>();
  if (!projectId || !compId || !subId) return null;
  return (
    <SubcomponentComparchShell
      projectId={projectId}
      compId={compId}
      subId={subId}
    />
  );
}

function SubcomponentComparchShell({
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
  const { data: subcomparch, error: subError } = useSubcomparch(
    projectId,
    compId,
    subId
  );

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

  if (subError) {
    return (
      <div className="fixed inset-0 bg-gray-900 z-50 flex items-center justify-center text-white">
        <div className="text-center max-w-xl px-6">
          <h1 className="text-xl font-bold text-red-400 mb-2">
            Failed to load subcomponent
          </h1>
          <p className="text-gray-400 text-sm">
            {describeApiError(subError, 'Unknown error')}
          </p>
          <Link
            to={`/projects/${projectId}/components/${compId}/comparch`}
            className="mt-4 inline-block px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm"
          >
            Back to Parent Component
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
              / {subName} / Subcomponent Arch Doc
            </span>
          </h1>
        </div>
        <Link
          to={`/projects/${projectId}/components/${compId}/comparch`}
          className="text-sm text-gray-400 hover:text-white"
        >
          ← Parent Comparch
        </Link>
      </header>
      <main className="flex-1 overflow-auto">
        <SubcomparchPanel
          projectId={projectId}
          parentCompId={compId}
          subId={subId}
          subName={subName}
        />
      </main>
    </div>
  );
}
