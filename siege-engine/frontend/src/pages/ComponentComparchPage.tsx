import { Link, useParams } from 'react-router-dom';
import { AppliedPolicyList } from '../components/AppliedPolicyList';
import { ComparchPanel } from '../components/ComparchPanel';
import { ComponentLocalPolicyList } from '../components/ComponentLocalPolicyList';
import { SubcomponentList } from '../components/SubcomponentList';
import { useComparch } from '../hooks/queries/useComparchQueries';
import { useImplTopLevel } from '../hooks/queries/useImplQueries';
import { useProject } from '../hooks/queries/useProjectQueries';
import { describeApiError } from '../lib/describeApiError';

/**
 * Full-page route for a single top-level component's architecture
 * doc. URL: ``/projects/:id/components/:compId/comparch``.
 *
 * Layout:
 * - Header with back link to dashboard + project name +
 *   component link breadcrumb
 * - ComparchPanel (four-state draft review)
 * - SubcomponentList (polling while mint might be running)
 * - ComponentLocalPolicyList
 * - AppliedPolicyList
 */
export function ComponentComparchPage() {
  const { id: projectId, compId } = useParams<{ id: string; compId: string }>();
  if (!projectId || !compId) return null;
  return <ComponentComparchShell projectId={projectId} compId={compId} />;
}

function ComponentComparchShell({
  projectId,
  compId,
}: {
  projectId: string;
  compId: string;
}) {
  const { data: project, error: projectError } = useProject(projectId);
  const { data: comparch } = useComparch(projectId, compId);
  const isApproved = !!comparch?.node.content;
  // Top-level impl exists only when the comp is un-fanned-out.
  // We query it unconditionally; the hook swallows 404 and
  // ``data`` stays undefined on fanned-out comps.
  const { data: implData } = useImplTopLevel(projectId, compId);
  const hasTopLevelImpl = !!implData;

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
              / {comparch?.node.name || compId} / Architecture Doc
            </span>
          </h1>
        </div>
        {hasTopLevelImpl && (
          <Link
            to={`/projects/${projectId}/components/${compId}/impl`}
            className="text-sm text-gray-400 hover:text-white"
          >
            Implementation →
          </Link>
        )}
        <Link
          to={`/projects/${projectId}/components/${compId}/subreqs`}
          className="text-sm text-gray-400 hover:text-white"
        >
          ← Subrequirements
        </Link>
      </header>
      <main className="flex-1 overflow-auto">
        <ComparchPanel
          projectId={projectId}
          componentId={compId}
          componentName={comparch?.node.name || compId}
        />
        {isApproved && (
          <>
            <SubcomponentList
              projectId={projectId}
              componentId={compId}
              mintPending={isApproved}
            />
            <ComponentLocalPolicyList
              projectId={projectId}
              componentId={compId}
              mintPending={isApproved}
            />
            <AppliedPolicyList projectId={projectId} componentId={compId} />
          </>
        )}
      </main>
    </div>
  );
}
