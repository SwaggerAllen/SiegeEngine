import { useState, useMemo, useEffect, Suspense, memo } from 'react';
import { useSafeEffect } from '../hooks/useSafe';
import { useParams, useSearchParams, useNavigate, useLocation, Link, Outlet, Navigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { useDAGStore } from '../store/dagStore';
import { usePipelineUIStore } from '../store/pipelineUIStore';
import { useProject } from '../hooks/queries/useProjectQueries';
import { useCurrentRunNumber, useIsRunning } from '../hooks/queries/usePipelineQueries';
import { useWebSocket } from '../hooks/useWebSocket';
import { useVisibilityRefresh } from '../hooks/useVisibilityRefresh';
import { TabSkeleton } from '../components/DashboardSkeleton';
import { HeaderDrawer } from '../components/layout/HeaderDrawer';
import api from '../api/client';
import { debugLog } from '../lib/debugLog';
import type { StageExecution } from '../schemas/pipeline';
import type { Artifact } from '../types/project';

/**
 * Find the most relevant StageExecution for a selected artifact.
 *
 * Fallback priority:
 * 1. Exact artifact match + awaiting_review (show Approve/Reject)
 * 2. Exact artifact match, any status
 * 3. Component key match, no artifact_id yet (generation died before artifact was created)
 * 4. Component key match, both awaiting_review (regeneration edge case with stale artifact_id)
 *
 * Input docs (project_doc) skip component_key fallbacks — they have no StageExecution.
 */
export function findSelectedExecution(
  executions: StageExecution[],
  artifact: Artifact,
): StageExecution | undefined {
  const isInputDoc = artifact.artifact_type === 'project_doc';
  return (
    // 1. Awaiting review for this artifact (needs user action)
    executions.find((e) => e.artifact_id === artifact.id && e.status === 'awaiting_review') ??
    // 2. Active generation for this component (running/pending — show live timer)
    (!isInputDoc
      ? executions.find(
          (e) =>
            !e.artifact_id &&
            e.component_key === (artifact.component_key ?? null) &&
            ['running', 'ai_review', 'pending'].includes(e.status) &&
            ['generating', 'ai_reviewing', 'pending'].includes(artifact.status),
        )
      : undefined) ??
    // 3. Historical execution that produced this artifact
    executions.find((e) => e.artifact_id === artifact.id) ??
    // 4. Failed execution for this component
    (!isInputDoc
      ? executions.find(
          (e) =>
            !e.artifact_id &&
            e.component_key === (artifact.component_key ?? null) &&
            ['failed', 'awaiting_review'].includes(e.status) &&
            ['generating', 'ai_reviewing', 'pending', 'awaiting_review'].includes(artifact.status),
        )
      : undefined) ??
    // 5. Awaiting review by component key
    (!isInputDoc
      ? executions.find(
          (e) =>
            e.component_key === (artifact.component_key ?? null) &&
            e.status === 'awaiting_review' &&
            artifact.status === 'awaiting_review',
        )
      : undefined)
  );
}

type Tab = 'documents' | 'pipeline' | 'prompts' | 'input-docs' | 'chat' | 'settings' | 'history' | 'logs' | 'debug';

const tabLabels: Record<Tab, string> = {
  documents: 'Documents',
  pipeline: 'Pipeline',
  prompts: 'Prompts',
  'input-docs': 'Input Docs',
  chat: 'Chat',
  settings: 'Settings',
  history: 'Event History',
  logs: 'Logs',
  debug: 'Debug',
};

// ---------------------------------------------------------------------------
// ProjectDashboardLayout — thin route wrapper, no hooks beyond params
// ---------------------------------------------------------------------------

export function ProjectDashboardLayout() {
  const { id: projectId } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();

  // Legacy ?tab=X redirect — one-time migration
  const legacyTab = searchParams.get('tab');
  if (legacyTab && projectId) {
    return <Navigate to={`/projects/${projectId}/${legacyTab}`} replace />;
  }

  if (!projectId) return null;
  return <DashboardLayout projectId={projectId} />;
}

// ---------------------------------------------------------------------------
// DashboardLayout — layout skeleton only
//
// No TQ subscriptions beyond what DashboardHeader needs.
// Tabs that need artifact/execution data (DocumentsTab, PipelineTab) fetch
// it themselves via useParams + useDAGStore + useArtifact + useExecutions.
// ---------------------------------------------------------------------------

function DashboardLayout({ projectId }: { projectId: string }) {
  const navigate = useNavigate();
  const location = useLocation();

  const editPromptStageKey = useDAGStore((s) => s.editPromptStageKey);
  const setEditPromptStageKey = useDAGStore((s) => s.setEditPromptStageKey);

  // Auth: only role check for visibleTabs
  const user = useAuthStore((s) => s.user);

  // Lifecycle logging — helps diagnose doom-loop remounts
  useEffect(() => {
    debugLog('DashboardLayout.lifecycle', `MOUNT projectId=${projectId}`);
    return () => { debugLog('DashboardLayout.lifecycle', `UNMOUNT projectId=${projectId}`); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reset UI state when project changes
  useEffect(() => {
    usePipelineUIStore.getState().reset();
    return () => { useDAGStore.getState().clearSelection(); };
  }, [projectId]);

  // Edit-prompt redirect: DAG node "Edit" → navigate to prompts tab
  useSafeEffect('edit-prompt-redirect', () => {
    if (editPromptStageKey) {
      navigate('prompts', { state: { initialStageKey: editPromptStageKey } });
      setEditPromptStageKey(null);
    }
  }, [editPromptStageKey, setEditPromptStageKey, navigate]);

  const pathSegments = location.pathname.split('/');
  const activeTab = (pathSegments[pathSegments.length - 1] || 'documents') as Tab;

  const isViewer = user?.role === 'viewer';
  const visibleTabs = useMemo<Tab[]>(
    () =>
      isViewer
        ? ['documents', 'pipeline', 'chat']
        : ['documents', 'pipeline', 'prompts', 'input-docs', 'chat', 'settings', 'history'],
    [isViewer],
  );

  return (
    <div className="h-screen flex flex-col bg-gray-900 text-white">
      <DashboardHeader projectId={projectId} visibleTabs={visibleTabs} activeTab={activeTab} />
      <Suspense fallback={<TabSkeleton />}>
        <Outlet />
      </Suspense>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DashboardHeader — all TQ header queries + dialogs
//
// Isolated so that project/pipeline data updates only re-render the header,
// not the outlet and its children.
// ---------------------------------------------------------------------------

const DashboardHeader = memo(function DashboardHeader({
  projectId,
  visibleTabs,
  activeTab,
}: {
  projectId: string;
  visibleTabs: Tab[];
  activeTab: Tab;
}) {
  // TQ subscriptions owned by this component
  const { data: currentProject, error: projectError } = useProject(projectId);
  const currentRunNumber = useCurrentRunNumber(projectId);
  const isRunning = useIsRunning(projectId);

  // WS lives here so its state changes (connected/reconnecting) don't touch the outlet
  const { connected, reconnect } = useWebSocket(projectId);
  useVisibilityRefresh(projectId, reconnect);

  // Zustand
  const isViewingHistory = usePipelineUIStore((s) => s.isViewingHistory);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const pageName = tabLabels[activeTab] ?? tabLabels.documents;

  if (projectError) {
    return (
      <div className="fixed inset-0 bg-gray-900 z-50 flex items-center justify-center text-white">
        <div className="text-center">
          <h1 className="text-xl font-bold text-red-400 mb-2">Failed to load project</h1>
          <p className="text-gray-400 text-sm">
            {projectError instanceof Error ? projectError.message : 'Unknown error'}
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
    <>
      <header className="border-b border-gray-700 px-3 py-2 flex items-center gap-3 shrink-0">
        <button
          onClick={() => setDrawerOpen(true)}
          className="p-2 text-gray-400 hover:text-white shrink-0"
          aria-label="Open menu"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <h1 className="text-sm font-bold truncate">{currentProject?.name || 'Loading...'}</h1>
            {isRunning && currentRunNumber && (
              <span className="text-xs bg-blue-600/30 text-blue-300 px-1.5 py-0.5 rounded-full border border-blue-500/30 shrink-0">
                #{currentRunNumber}
              </span>
            )}
            {isViewingHistory && (
              <span className="text-xs bg-yellow-600/30 text-yellow-300 px-1.5 py-0.5 rounded-full border border-yellow-500/30 shrink-0">
                History
              </span>
            )}
          </div>
          <p className="text-xs text-gray-400 leading-none mt-0.5">{pageName}</p>
        </div>
        {!connected && (
          <button
            onClick={reconnect}
            className="text-xs text-yellow-400 animate-pulse hover:text-yellow-300 shrink-0"
            title="Click to reconnect WebSocket"
          >
            WS↻
          </button>
        )}
      </header>
      {drawerOpen && (
        <HeaderDrawer
          projectId={projectId}
          visibleTabs={visibleTabs}
          onClose={() => setDrawerOpen(false)}
        />
      )}
    </>
  );
});


// ---------------------------------------------------------------------------
// PRDialog — standalone, no shared state dependencies
// ---------------------------------------------------------------------------

export function PRDialog({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [baseBranch, setBaseBranch] = useState('main');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ pr_url?: string; error?: string } | null>(null);

  const handleSubmit = async () => {
    setLoading(true);
    setResult(null);
    try {
      const { data } = await api.post(`/projects/${projectId}/open-pr`, {
        title,
        body,
        base_branch: baseBranch,
      });
      setResult({ pr_url: data.pr_url });
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setResult({ error: detail || 'Failed to create PR' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-white">Open Pull Request</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl min-h-[44px] min-w-[44px]">
            &times;
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-sm text-gray-300 mb-1">Title</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-300 mb-1">Description</label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={4}
              className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-300 mb-1">Base Branch</label>
            <input
              value={baseBranch}
              onChange={(e) => setBaseBranch(e.target.value)}
              className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
            />
          </div>

          {result?.pr_url && (
            <p className="text-green-400 text-sm">
              PR created:{' '}
              <a href={result.pr_url} target="_blank" rel="noreferrer" className="underline">
                {result.pr_url}
              </a>
            </p>
          )}
          {result?.error && <p className="text-red-400 text-sm">{result.error}</p>}

          <button
            onClick={handleSubmit}
            disabled={loading || !title}
            className="w-full py-2 bg-purple-600 hover:bg-purple-700 text-white rounded text-sm disabled:opacity-50"
          >
            {loading ? 'Creating...' : 'Create Pull Request'}
          </button>
        </div>
      </div>
    </div>
  );
}
