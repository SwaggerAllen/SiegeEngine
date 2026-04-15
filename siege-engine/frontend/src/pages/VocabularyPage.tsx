import { Link, useParams } from 'react-router-dom';
import { VocabularyList } from '../components/VocabularyList';
import { useProject } from '../hooks/queries/useProjectQueries';
import { describeApiError } from '../lib/describeApiError';

/**
 * Full-page vocabulary browser + editor. URL:
 * ``/projects/:id/vocabulary``.
 *
 * Split-pane layout: the left side is the list of every
 * project-level and feature-local vocab entry; the right side
 * is the detail panel for whichever entry is currently
 * selected. A "+ Add term" button opens the creation dialog.
 *
 * Editing, deleting, renaming, and reparenting are all done
 * through direct routes without an LLM; the LLM-assisted
 * feedback → regen flow is deferred to a follow-up.
 */
export function VocabularyPage() {
  const { id: projectId } = useParams<{ id: string }>();
  if (!projectId) return null;
  return <VocabularyShell projectId={projectId} />;
}

function VocabularyShell({ projectId }: { projectId: string }) {
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
            <span className="text-gray-500 font-normal">/ Vocabulary</span>
          </h1>
        </div>
      </header>
      <main className="flex-1 overflow-hidden">
        <VocabularyList projectId={projectId} />
      </main>
    </div>
  );
}
