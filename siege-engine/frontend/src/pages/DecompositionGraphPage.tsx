import { Link, useParams } from 'react-router-dom';
import { DecompositionGraph } from '../components/DecompositionGraph';
import { useDecompositionGraph } from '../hooks/queries/useDecompositionGraph';
import { useProject } from '../hooks/queries/useProjectQueries';
import { describeApiError } from '../lib/describeApiError';

/**
 * Full-page Cytoscape view of the project's decomposition graph.
 * URL: ``/projects/:id/decomposition``.
 *
 * Read-only for Phase 4 — displays components, subcomponents,
 * resps, subresps, dependency edges, decomposition edges, and
 * domain_parent edges as a force-directed layout. Editing the
 * graph lands in Phase 11 structural-edit UIs.
 */
export function DecompositionGraphPage() {
  const { id: projectId } = useParams<{ id: string }>();
  if (!projectId) return null;
  return <DecompositionGraphShell projectId={projectId} />;
}

function DecompositionGraphShell({ projectId }: { projectId: string }) {
  const { data: project, error: projectError } = useProject(projectId);
  const { data: graph, error: graphError, isLoading } = useDecompositionGraph(
    projectId
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
              / Decomposition Graph
            </span>
          </h1>
        </div>
        <div className="text-xs text-gray-500 flex items-center gap-4">
          <span>
            <span className="inline-block w-2 h-2 bg-blue-500 mr-1" />
            component
          </span>
          <span>
            <span className="inline-block w-2 h-2 bg-purple-500 mr-1" />
            presentational
          </span>
          <span>
            <span className="inline-block w-2 h-2 bg-green-500 mr-1" />
            resp
          </span>
          <span>— —</span>
          <span>decomposition</span>
          <span>—</span>
          <span>dependency</span>
        </div>
      </header>
      <main className="flex-1 overflow-hidden">
        {isLoading && (
          <div className="h-full flex items-center justify-center text-gray-400">
            Loading decomposition graph…
          </div>
        )}
        {graphError && (
          <div className="h-full flex items-center justify-center text-red-400 px-6 text-sm">
            {describeApiError(graphError, 'Failed to load decomposition graph')}
          </div>
        )}
        {graph && graph.nodes.length === 0 && (
          <div className="h-full flex items-center justify-center text-gray-500 italic px-6 text-sm">
            No components or responsibilities minted yet. Approve the
            requirements and system architecture to populate this graph.
          </div>
        )}
        {graph && graph.nodes.length > 0 && <DecompositionGraph graph={graph} />}
      </main>
    </div>
  );
}
