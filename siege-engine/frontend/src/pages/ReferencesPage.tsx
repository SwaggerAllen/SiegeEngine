import { Link, useParams } from 'react-router-dom';
import { ReferencesList } from '../components/ReferencesList';
import { useProject } from '../hooks/queries/useProjectQueries';
import { describeApiError } from '../lib/describeApiError';

/**
 * Full-page references browser (Phase 6.6). URL:
 * ``/projects/:id/references``.
 *
 * Split-pane layout: the left side lists every ``ref_*`` node in
 * the project; the right side is the detail panel for the
 * currently-selected ref (approved content, pending draft,
 * feedback form, edge editor).
 */
export function ReferencesPage() {
  const { id: projectId } = useParams<{ id: string }>();
  if (!projectId) return null;
  return <ReferencesShell projectId={projectId} />;
}

function ReferencesShell({ projectId }: { projectId: string }) {
  const { data: project, error: projectError } = useProject(projectId);

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
            <span className="text-gray-500 font-normal">/ References</span>
          </h1>
        </div>
      </header>
      <main className="flex-1 overflow-hidden">
        <ReferencesList projectId={projectId} />
      </main>
    </div>
  );
}
