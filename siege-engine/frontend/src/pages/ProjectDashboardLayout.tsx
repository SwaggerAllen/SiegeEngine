import { useRef, useState, Suspense } from 'react';
import { useSafeEffect } from '../hooks/useSafe';
import { useParams, useSearchParams, useNavigate, useLocation, Link, Outlet, Navigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useProjectStore } from '../store/projectStore';
import { useAuthStore } from '../store/authStore';
import { useDAGStore } from '../store/dagStore';
import { usePipelineUIStore } from '../store/pipelineUIStore';
import { useProject } from '../hooks/queries/useProjectQueries';
import { useExecutions, useCurrentRunNumber, useIsRunning, pipelineKeys } from '../hooks/queries/usePipelineQueries';
import { useWebSocket } from '../hooks/useWebSocket';
import { useVisibilityRefresh } from '../hooks/useVisibilityRefresh';
import { useProjectInit } from '../hooks/useProjectInit';
import { PipelineControls } from '../components/pipeline/PipelineControls';
import { InvitePanel } from '../components/auth/InvitePanel';
import { RunSelector } from '../components/pipeline/RunSelector';
import { DashboardSkeleton, TabSkeleton } from '../components/DashboardSkeleton';
import { reconcilePipeline } from '../api/pipeline';
import api from '../api/client';
import type { DashboardContext } from '../components/tabs/types';

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

export function ProjectDashboardLayout() {
  const { id: projectId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();

  // Legacy ?tab=X redirect — one-time migration
  const legacyTab = searchParams.get('tab');
  if (legacyTab && projectId) {
    return <Navigate to={`/projects/${projectId}/${legacyTab}`} replace />;
  }

  if (!projectId) return null;

  return <DashboardInner projectId={projectId} navigate={navigate} location={location} />;
}

function DashboardInner({
  projectId,
  navigate,
  location,
}: {
  projectId: string;
  navigate: ReturnType<typeof useNavigate>;
  location: ReturnType<typeof useLocation>;
}) {
  // TQ queries
  const queryClient = useQueryClient();
  const { data: currentProject } = useProject(projectId);
  const executions = useExecutions(projectId);
  const currentRunNumber = useCurrentRunNumber(projectId);
  const isRunning = useIsRunning(projectId);

  // Zustand stores (UI-only state)
  const selectedArtifact = useProjectStore((s) => s.selectedArtifact);
  const clearSelection = useProjectStore((s) => s.clearSelection);
  const isViewingHistory = usePipelineUIStore((s) => s.isViewingHistory);
  const user = useAuthStore((s) => s.user);
  const editPromptStageKey = useDAGStore((s) => s.editPromptStageKey);
  const setEditPromptStageKey = useDAGStore((s) => s.setEditPromptStageKey);

  // Initialization gate
  const { ready, error } = useProjectInit(projectId);

  // WebSocket + visibility refresh (stay in layout, persist across tab switches)
  const { connected, reconnect } = useWebSocket(projectId);
  useVisibilityRefresh(projectId, reconnect);

  // Track whether we've ever been ready — once true, never show the skeleton
  // again (prevents child unmount/remount on hard refresh refetch).
  const hasBeenReady = useRef(false);
  if (ready) hasBeenReady.current = true;
  const showSkeleton = !hasBeenReady.current && !ready;

  // Local UI state
  const [showInvites, setShowInvites] = useState(false);
  const [showPRDialog, setShowPRDialog] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [repairResult, setRepairResult] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close hamburger menu on outside click
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

  // Edit-prompt redirect: DAG node "Edit" → navigate to prompts tab
  useSafeEffect('edit-prompt-redirect', () => {
    if (editPromptStageKey) {
      navigate('prompts', { state: { initialStageKey: editPromptStageKey } });
      setEditPromptStageKey(null);
    }
  }, [editPromptStageKey, setEditPromptStageKey, navigate]);

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

  // Derive active tab from URL path
  const pathSegments = location.pathname.split('/');
  const activeTab = (pathSegments[pathSegments.length - 1] || 'documents') as Tab;

  // Derive selectedExecution (complex matching logic preserved from original)
  const isInputDoc = selectedArtifact?.artifact_type === 'project_doc';
  const selectedExecution = selectedArtifact
    ? executions.find((e) => e.artifact_id === selectedArtifact.id && e.status === 'awaiting_review')
      || executions.find((e) => e.artifact_id === selectedArtifact.id)
      || (!isInputDoc && executions.find((e) =>
          !e.artifact_id
          && e.component_key === (selectedArtifact.component_key ?? null)
          && ['running', 'ai_review', 'failed', 'awaiting_review'].includes(e.status)
          && ['generating', 'ai_reviewing', 'pending', 'awaiting_review'].includes(selectedArtifact.status)
        ))
      || (!isInputDoc && executions.find((e) =>
          e.component_key === (selectedArtifact.component_key ?? null)
          && e.status === 'awaiting_review'
          && selectedArtifact.status === 'awaiting_review'
        ))
      || undefined
    : undefined;

  const isAdmin = user?.role === 'admin';
  const isViewer = user?.role === 'viewer';
  const hasRemote = !!currentProject?.remote_url;
  const visibleTabs: Tab[] = isViewer
    ? ['documents', 'pipeline', 'chat']
    : ['documents', 'pipeline', 'prompts', 'input-docs', 'chat', 'settings', 'history'];

  const outletContext: DashboardContext = { projectId, selectedArtifact, selectedExecution };

  if (error) {
    return (
      <div className="h-screen flex items-center justify-center bg-gray-900 text-white">
        <div className="text-center">
          <h1 className="text-xl font-bold text-red-400 mb-2">Failed to load project</h1>
          <p className="text-gray-400 text-sm">{error.message}</p>
          <Link to="/projects" className="mt-4 inline-block px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm">
            Back to Projects
          </Link>
        </div>
      </div>
    );
  }

  if (showSkeleton) {
    return (
      <div className="h-screen flex flex-col bg-gray-900 text-white">
        <DashboardSkeleton />
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-gray-900 text-white">
      {/* Header */}
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
          {!isViewer && !isViewingHistory && <PipelineControls projectId={projectId} hasGitHub={!!currentProject?.github_repo_slug} />}
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
            <svg className={`w-4 h-4 inline ${repairing ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {repairing ? (
                <>
                  <circle className="opacity-25" cx="12" cy="12" r="10" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" stroke="none" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </>
              ) : (
                <>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </>
              )}
            </svg>
          </button>
          {repairResult && (
            <span className={`text-xs ${repairResult.startsWith('Fixed') ? 'text-green-400' : repairResult === 'No issues found' ? 'text-gray-400' : 'text-red-400'}`}>
              {repairResult}
            </span>
          )}
          <button
            onClick={() => { navigate('debug'); clearSelection(); setMenuOpen(false); }}
            className={`px-2 py-1 text-xs rounded min-h-[44px] md:min-h-0 ${
              activeTab === 'debug'
                ? 'bg-yellow-600 text-white'
                : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
            }`}
            title="Debug State"
          >
            <svg className="w-4 h-4 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </button>
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

      {/* Navigation menu */}
      <div className="border-b border-gray-700 px-4 shrink-0 relative" ref={menuRef}>
        <button
          onClick={() => setMenuOpen(!menuOpen)}
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
              <button
                key={tab}
                onClick={() => { navigate(tab); clearSelection(); setMenuOpen(false); }}
                className={`w-full text-left px-4 py-3 text-sm ${
                  activeTab === tab
                    ? 'bg-gray-700 text-white'
                    : 'text-gray-300 hover:bg-gray-700 hover:text-white'
                }`}
              >
                {tabLabels[tab]}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Tab content via nested route */}
      <Suspense fallback={<TabSkeleton />}>
        <Outlet context={outletContext} />
      </Suspense>

      {showInvites && <InvitePanel onClose={() => setShowInvites(false)} />}
      {showPRDialog && (
        <PRDialog
          projectId={projectId}
          onClose={() => setShowPRDialog(false)}
        />
      )}
    </div>
  );
}

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
