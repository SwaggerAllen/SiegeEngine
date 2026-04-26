import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { DashboardMenu } from '../components/DashboardMenu';
import { NavDetail } from '../components/nav/NavDetail';
import { NavTree } from '../components/nav/NavTree';
import { TabStrip } from '../components/nav/TabStrip';
import { tabScope, type Tab } from '../components/nav/tabScope';
import { useProject } from '../hooks/queries/useProjectQueries';
import { useProjectEventStream } from '../hooks/queries/useProjectEventStream';
import { useProjectStructure } from '../hooks/queries/useProjectStructure';
import { useOpenReviewBatchMutation } from '../hooks/queries/useReviewBatch';
import { describeApiError } from '../lib/describeApiError';

/**
 * Primary project workspace. Replaces the old tabbed
 * ProjectDashboardLayout with a sidebar tree + detail pane.
 *
 * Layout semantics:
 * - Desktop (md+): sidebar is a persistent left column (280px),
 *   toggle button in the header collapses it. State persists to
 *   localStorage so the user's preference survives reloads.
 * - Mobile (<md): sidebar is hidden by default, toggle button
 *   opens it as a full-height overlay drawer with a backdrop.
 *   Tapping a leaf auto-closes the drawer so the detail pane
 *   takes over the viewport.
 *
 * Selection URL scheme: ``/projects/:id?node=<id>``. The ``node``
 * query param is the source of truth — direct links land the
 * user on the right node with ancestors auto-expanded.
 */
export function ProjectWorkspacePage() {
  const { id: projectId } = useParams<{ id: string }>();
  if (!projectId) return null;
  return <WorkspaceShell projectId={projectId} />;
}

const SIDEBAR_OPEN_STORAGE_KEY = 'siege.workspace.sidebarOpen';

function WorkspaceShell({ projectId }: { projectId: string }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const selectedId = searchParams.get('node');
  const view = searchParams.get('view');

  const { data: project, error: projectError } = useProject(projectId);
  const { data: structure, error: navError } = useProjectStructure(projectId);
  const openReviewMutation = useOpenReviewBatchMutation(projectId);

  // One EventSource per mounted project page. Drives all cache
  // invalidations for this project; per-tier query hooks drop
  // their ``refetchInterval`` polling because the stream is
  // now the refetch trigger.
  useProjectEventStream(projectId);

  // Desktop sidebar collapsed/expanded state. On mobile this also
  // controls the drawer; we reset it to closed on mount so mobile
  // never lands with the drawer already overlaying.
  const [desktopOpen, setDesktopOpen] = useState<boolean>(() => {
    const stored = localStorage.getItem(SIDEBAR_OPEN_STORAGE_KEY);
    return stored === null ? true : stored === 'true';
  });
  const [mobileOpen, setMobileOpen] = useState<boolean>(false);

  useEffect(() => {
    localStorage.setItem(SIDEBAR_OPEN_STORAGE_KEY, String(desktopOpen));
  }, [desktopOpen]);

  const handleSelect = useCallback(
    (id: string) => {
      // Sidebar selection clears ``?view=`` so the user lands on
      // the destination node's default view. Tab clicks set view
      // explicitly via ``handleSelectTab`` instead.
      const next = new URLSearchParams(searchParams);
      next.set('node', id);
      next.delete('view');
      setSearchParams(next, { replace: false });
    },
    [searchParams, setSearchParams],
  );

  const handleSelectTab = useCallback(
    (tab: Tab) => {
      const next = new URLSearchParams(searchParams);
      next.set('node', tab.targetNodeId);
      if (tab.targetView) {
        next.set('view', tab.targetView);
      } else {
        next.delete('view');
      }
      setSearchParams(next, { replace: false });
    },
    [searchParams, setSearchParams],
  );

  const handleLeafSelect = useCallback(() => {
    // Auto-close the mobile drawer when a leaf is picked. The
    // desktop sidebar stays open — users want to see the tree
    // context even after selection.
    setMobileOpen(false);
  }, []);

  const toggleSidebar = useCallback(() => {
    // On desktop, collapse the persistent sidebar. On mobile,
    // open the drawer overlay. Detect via viewport; we use the
    // same media query the Tailwind ``md:`` prefix uses.
    const isDesktop =
      typeof window !== 'undefined' &&
      window.matchMedia('(min-width: 768px)').matches;
    if (isDesktop) {
      setDesktopOpen((v) => !v);
    } else {
      setMobileOpen((v) => !v);
    }
  }, []);

  const nodes = useMemo(() => structure?.nodes ?? [], [structure]);
  const edges = useMemo(() => structure?.edges ?? [], [structure]);
  const selectedNode = selectedId ? nodes.find((n) => n.id === selectedId) : null;
  const breadcrumb = selectedNode?.name ?? breadcrumbForSyntheticId(selectedId);
  const scope = useMemo(
    () => tabScope(selectedId, view, nodes),
    [selectedId, view, nodes],
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
    <div className="h-screen flex flex-col bg-gray-900 text-white overflow-hidden">
      <header className="border-b border-gray-700 px-3 py-2 flex items-center gap-2 shrink-0">
        <button
          type="button"
          aria-label={mobileOpen || desktopOpen ? 'Hide navigation' : 'Show navigation'}
          onClick={toggleSidebar}
          className="shrink-0 w-8 h-8 rounded border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 flex items-center justify-center"
          title="Toggle navigation"
        >
          ☰
        </button>
        <Link to="/projects" className="text-sm text-gray-400 hover:text-white shrink-0">
          ←
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-sm font-bold truncate">
            {project?.name || 'Loading…'}
            {breadcrumb && (
              <span className="text-gray-500 font-normal"> / {breadcrumb}</span>
            )}
          </h1>
        </div>
        <button
          type="button"
          onClick={() => {
            openReviewMutation.mutate(undefined, {
              onSuccess: (batch) => {
                navigate(`/projects/${projectId}/review/${batch.id}`);
              },
            });
          }}
          disabled={openReviewMutation.isPending}
          className="px-2 py-1 text-xs rounded border border-gray-700 text-gray-300 hover:bg-gray-800 hover:text-white disabled:opacity-40 shrink-0"
          title="Open a batched review of stale nodes"
        >
          Review
        </button>
        <DashboardMenu projectId={projectId} />
      </header>

      <div className="flex-1 flex min-h-0 relative">
        {/* Desktop sidebar — persistent column that collapses */}
        <aside
          className={`hidden md:block shrink-0 border-r border-gray-700 bg-gray-950 overflow-y-auto transition-[width] duration-150 ${
            desktopOpen ? 'w-72' : 'w-0'
          }`}
          aria-hidden={!desktopOpen}
        >
          {desktopOpen && (
            <div className="p-2">
              {navError ? (
                <p className="text-xs text-red-400 p-2">
                  {describeApiError(navError, 'Failed to load nav')}
                </p>
              ) : (
                <NavTree
                  nodes={nodes}
                  edges={edges}
                  selectedId={selectedId}
                  onSelect={handleSelect}
                />
              )}
            </div>
          )}
        </aside>

        {/* Mobile drawer — overlay with backdrop */}
        {mobileOpen && (
          <>
            <button
              type="button"
              aria-label="Close navigation"
              className="md:hidden fixed inset-0 z-40 bg-black/60"
              onClick={() => setMobileOpen(false)}
            />
            <aside
              className="md:hidden fixed top-12 left-0 bottom-0 z-50 w-72 max-w-[85vw] border-r border-gray-700 bg-gray-950 overflow-y-auto"
              aria-label="Project navigation"
            >
              <div className="p-2">
                {navError ? (
                  <p className="text-xs text-red-400 p-2">
                    {describeApiError(navError, 'Failed to load nav')}
                  </p>
                ) : (
                  <NavTree
                    nodes={nodes}
                    edges={edges}
                    selectedId={selectedId}
                    onSelect={handleSelect}
                    onLeafSelect={handleLeafSelect}
                  />
                )}
              </div>
            </aside>
          </>
        )}

        <main className="flex-1 min-w-0 overflow-hidden flex flex-col">
          <TabStrip scope={scope} onSelectTab={handleSelectTab} />
          <div className="flex-1 min-h-0 overflow-hidden">
            <NavDetail
              projectId={projectId}
              selectedId={selectedId}
              nodes={nodes}
              view={view}
            />
          </div>
        </main>
      </div>
    </div>
  );
}

function breadcrumbForSyntheticId(selectedId: string | null): string | null {
  if (!selectedId) return null;
  switch (selectedId) {
    case ':vocabulary':
      return 'Vocabulary';
    case ':references':
      return 'References';
    case ':dag':
      return 'Decomposition Graph';
    case ':queue':
      return 'Pending Changes';
    default:
      return null;
  }
}
