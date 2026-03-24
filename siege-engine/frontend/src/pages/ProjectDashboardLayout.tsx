import { useState, useMemo, useEffect, Suspense, memo, useRef } from 'react';
import { useSafeEffect } from '../hooks/useSafe';
import { useParams, useSearchParams, useNavigate, useLocation, Link, NavLink, Outlet, Navigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '../store/authStore';
import { useDAGStore } from '../store/dagStore';
import { usePipelineUIStore } from '../store/pipelineUIStore';
import { useProject } from '../hooks/queries/useProjectQueries';
import { useCurrentRunNumber, useIsRunning, pipelineKeys } from '../hooks/queries/usePipelineQueries';
import { useWebSocket } from '../hooks/useWebSocket';
import { useVisibilityRefresh } from '../hooks/useVisibilityRefresh';
import { PipelineControls } from '../components/pipeline/PipelineControls';
import { InvitePanel } from '../components/auth/InvitePanel';
import { RunSelector } from '../components/pipeline/RunSelector';
import { TabSkeleton } from '../components/DashboardSkeleton';
import { reconcilePipeline } from '../api/pipeline';
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
    executions.find((e) => e.artifact_id === artifact.id && e.status === 'awaiting_review') ??
    executions.find((e) => e.artifact_id === artifact.id) ??
    (!isInputDoc
      ? executions.find(
          (e) =>
            !e.artifact_id &&
            e.component_key === (artifact.component_key ?? null) &&
            ['running', 'ai_review', 'failed', 'awaiting_review'].includes(e.status) &&
            ['generating', 'ai_reviewing', 'pending', 'awaiting_review'].includes(artifact.status),
        )
      : undefined) ??
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
      <DashboardHeader projectId={projectId} />
      <DashboardNav visibleTabs={visibleTabs} activeTab={activeTab} />
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
}: {
  projectId: string;
}) {
  const queryClient = useQueryClient();

  // TQ subscriptions owned by this component
  const { data: currentProject, error: projectError } = useProject(projectId);
  const currentRunNumber = useCurrentRunNumber(projectId);
  const isRunning = useIsRunning(projectId);

  // WS lives here so its state changes (connected/reconnecting) don't touch the outlet
  const { connected, reconnect } = useWebSocket(projectId);
  useVisibilityRefresh(projectId, reconnect);

  // Zustand
  const user = useAuthStore((s) => s.user);
  const isViewingHistory = usePipelineUIStore((s) => s.isViewingHistory);
  const clearSelection = useDAGStore((s) => s.clearSelection);

  const isAdmin = user?.role === 'admin';
  const isViewer = user?.role === 'viewer';
  const hasRemote = !!currentProject?.remote_url;

  // Local dialog + repair state — changes only re-render this component
  const [showInvites, setShowInvites] = useState(false);
  const [showPRDialog, setShowPRDialog] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [repairResult, setRepairResult] = useState<string | null>(null);

  const handleRepair = async () => {
    if (repairing) return;
    setRepairing(true);
    setRepairResult(null);
    try {
      const result = await reconcilePipeline(projectId);
      const fixes = result.corrections.length + result.orphans_removed.length;
      setRepairResult(fixes > 0 ? `Fixed ${fixes} issue${fixes > 1 ? 's' : ''}` : 'No issues found');
      if (fixes > 0) {
        queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
        queryClient.invalidateQueries({ queryKey: pipelineKeys.runs(projectId) });
      }
    } catch {
      setRepairResult('Repair failed');
    } finally {
      setRepairing(false);
      setTimeout(() => setRepairResult(null), 4000);
    }
  };

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
      <header className="border-b border-gray-700 px-3 md:px-4 py-2 md:py-3 flex flex-wrap items-center justify-between gap-2 shrink-0">
        <div className="flex items-center gap-2 md:gap-4 min-w-0">
          <Link to="/projects" className="text-gray-400 hover:text-white text-sm shrink-0">
            &larr; Projects
          </Link>
          <h1 className="text-sm md:text-lg font-bold truncate">
            {currentProject?.name || 'Loading...'}
          </h1>
          {isRunning && currentRunNumber && (
            <span className="text-xs bg-blue-600/30 text-blue-300 px-2 py-0.5 rounded-full border border-blue-500/30 shrink-0">
              Run #{currentRunNumber}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 md:gap-4 flex-wrap">
          <RunSelector projectId={projectId} />
          {!isViewer && !isViewingHistory && (
            <PipelineControls projectId={projectId} hasGitHub={!!currentProject?.github_repo_slug} />
          )}
          {isViewingHistory && (
            <span className="text-xs bg-yellow-600/30 text-yellow-300 px-2 py-0.5 rounded-full border border-yellow-500/30">
              Viewing history (read-only)
            </span>
          )}
          {!isViewer && hasRemote && !isViewingHistory && (
            <button
              onClick={() => setShowPRDialog(true)}
              className="px-2 py-1 bg-purple-600 hover:bg-purple-700 text-white text-xs rounded min-h-[44px] md:min-h-0"
            >
              Open PR
            </button>
          )}
          {isAdmin && (
            <button
              onClick={() => setShowInvites(true)}
              className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded min-h-[44px] md:min-h-0"
            >
              Invites
            </button>
          )}
          <button
            onClick={handleRepair}
            disabled={repairing}
            className="px-2 py-1 text-xs rounded min-h-[44px] md:min-h-0 bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-50"
            title="Repair: fix status mismatches and stuck runs"
          >
            <svg
              className={`w-4 h-4 inline ${repairing ? 'animate-spin' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              {repairing ? (
                <>
                  <circle className="opacity-25" cx="12" cy="12" r="10" strokeWidth="4" />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    stroke="none"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </>
              ) : (
                <>
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
                  />
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                  />
                </>
              )}
            </svg>
          </button>
          {repairResult && (
            <span
              className={`text-xs ${
                repairResult.startsWith('Fixed')
                  ? 'text-green-400'
                  : repairResult === 'No issues found'
                  ? 'text-gray-400'
                  : 'text-red-400'
              }`}
            >
              {repairResult}
            </span>
          )}
          <NavLink
            to="debug"
            onClick={clearSelection}
            className={({ isActive }) =>
              `px-2 py-1 text-xs rounded min-h-[44px] md:min-h-0 ${
                isActive
                  ? 'bg-yellow-600 text-white'
                  : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
              }`
            }
            title="Debug State"
          >
            <svg className="w-4 h-4 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </NavLink>
          {connected ? (
            <span className="text-xs text-green-400">WS Connected</span>
          ) : (
            <button
              onClick={reconnect}
              className="text-xs text-yellow-400 animate-pulse hover:text-yellow-300 cursor-pointer"
              title="Click to reconnect now"
            >
              WS Reconnecting...
            </button>
          )}
        </div>
      </header>
      {showInvites && <InvitePanel onClose={() => setShowInvites(false)} />}
      {showPRDialog && (
        <PRDialog projectId={projectId} onClose={() => setShowPRDialog(false)} />
      )}
    </>
  );
});

// ---------------------------------------------------------------------------
// DashboardNav — hamburger menu with fully local state
//
// menuOpen lives here so toggling it never re-renders DashboardInner or
// the outlet. No TQ subscriptions.
// ---------------------------------------------------------------------------

const DashboardNav = memo(function DashboardNav({
  visibleTabs,
  activeTab,
}: {
  visibleTabs: Tab[];
  activeTab: Tab;
}) {
  const clearSelection = useDAGStore((s) => s.clearSelection);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close the menu whenever the active tab changes (e.g. debug button in header)
  useEffect(() => {
    setMenuOpen(false);
  }, [activeTab]);

  // Close on outside click
  useSafeEffect('menu-outside-click', () => {
    if (!menuOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [menuOpen]);

  return (
    <div className="border-b border-gray-700 px-4 shrink-0 relative" ref={menuRef}>
      <button
        onClick={() => setMenuOpen((o) => !o)}
        className="flex items-center gap-2 py-2 text-sm text-gray-300 hover:text-white min-h-[44px]"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
        <span>{tabLabels[activeTab] || tabLabels.documents}</span>
      </button>
      {menuOpen && (
        <div className="absolute left-0 top-full z-50 w-48 bg-gray-800 border border-gray-700 rounded-b-lg shadow-xl">
          {visibleTabs.map((tab) => (
            <NavLink
              key={tab}
              to={tab}
              onClick={() => { clearSelection(); setMenuOpen(false); }}
              className={({ isActive }) =>
                `block w-full text-left px-4 py-3 text-sm ${
                  isActive
                    ? 'bg-gray-700 text-white'
                    : 'text-gray-300 hover:bg-gray-700 hover:text-white'
                }`
              }
            >
              {tabLabels[tab]}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
});

// ---------------------------------------------------------------------------
// PRDialog — standalone, no shared state dependencies
// ---------------------------------------------------------------------------

function PRDialog({ projectId, onClose }: { projectId: string; onClose: () => void }) {
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
