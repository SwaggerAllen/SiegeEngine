import { useRef, useState } from 'react';
import { useSafeEffect } from '../hooks/useSafe';
import { useParams, Link } from 'react-router-dom';
import { useProjectStore } from '../store/projectStore';
import { usePipelineStore } from '../store/pipelineStore';
import { useAuthStore } from '../store/authStore';
import { useDAGStore } from '../store/dagStore';
import { useWebSocket } from '../hooks/useWebSocket';
import { useVisibilityRefresh } from '../hooks/useVisibilityRefresh';
// TEMP: commented out to isolate crash source
// import { PipelineDAG } from '../components/dag/PipelineDAG';
import { PipelineControls } from '../components/pipeline/PipelineControls';
import { StageStatusList } from '../components/pipeline/StageStatus';
import { ArtifactEditor } from '../components/editor/ArtifactEditor';
import { ReviewPanel } from '../components/pipeline/ReviewPanel';
import { InvitePanel } from '../components/auth/InvitePanel';
import { PromptEditorPanel } from '../components/pipeline/PromptEditorPanel';
import { StageConfigPanel } from '../components/pipeline/StageConfigPanel';
import { ProjectSettingsPanel } from '../components/project/ProjectSettingsPanel';
import { ChatPanel } from '../components/chat/ChatPanel';
import InputDocsPanel from '../components/input-docs/InputDocsPanel';
import { RunSelector } from '../components/pipeline/RunSelector';
import { EventHistoryPanel } from '../components/pipeline/EventHistoryPanel';
import { LogPanel } from '../components/pipeline/LogPanel';
import { DebugStatePanel } from '../components/pipeline/DebugStatePanel';
import { PanelErrorBoundary } from '../components/ErrorBoundary';
import { ErrorLogPanel } from '../components/pipeline/ErrorLogPanel';
import { useErrorLogStore } from '../store/errorLogStore';
import { reconcilePipeline } from '../api/pipeline';
import api from '../api/client';

type Tab = 'documents' | 'pipeline' | 'prompts' | 'input-docs' | 'chat' | 'settings' | 'history' | 'logs' | 'debug' | 'errors';

export function ProjectDashboardPage() {
  const { id: projectId } = useParams<{ id: string }>();
  // Use individual selectors to avoid re-rendering on every unrelated store change.
  // Without selectors, usePipelineStore() re-renders this component on every WS event.
  const currentProject = useProjectStore((s) => s.currentProject);
  const fetchProject = useProjectStore((s) => s.fetchProject);
  const selectedArtifact = useProjectStore((s) => s.selectedArtifact);
  const clearSelection = useProjectStore((s) => s.clearSelection);
  const executions = usePipelineStore((s) => s.executions);
  const fetchConfig = usePipelineStore((s) => s.fetchConfig);
  const fetchStatus = usePipelineStore((s) => s.fetchStatus);
  const fetchRuns = usePipelineStore((s) => s.fetchRuns);
  const fetchBlockingPR = usePipelineStore((s) => s.fetchBlockingPR);
  const currentRunNumber = usePipelineStore((s) => s.currentRunNumber);
  const isRunning = usePipelineStore((s) => s.isRunning);
  const isViewingHistory = usePipelineStore((s) => s.isViewingHistory);
  const resetPipeline = usePipelineStore((s) => s.reset);
  const user = useAuthStore((s) => s.user);
  const editPromptStageKey = useDAGStore((s) => s.editPromptStageKey);
  const setEditPromptStageKey = useDAGStore((s) => s.setEditPromptStageKey);
  const selectedStageKey = useDAGStore((s) => s.selectedStageKey);
  const { connected, reconnect } = useWebSocket(projectId);
  const errorCount = useErrorLogStore((s) => s.errors.length);
  useVisibilityRefresh(projectId, reconnect);
  const [showInvites, setShowInvites] = useState(false);
  const [showPRDialog, setShowPRDialog] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>('documents');
  const [paneExpanded, setPaneExpanded] = useState(false);
  const [initialStageKey, setInitialStageKey] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [repairResult, setRepairResult] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useSafeEffect('dashboard-init', () => {
    resetPipeline();
    if (projectId) {
      fetchProject(projectId);
      fetchConfig(projectId);
      fetchStatus(projectId);
      fetchRuns(projectId);
      fetchBlockingPR(projectId);
    }
    return () => clearSelection();
  }, [projectId, resetPipeline, fetchProject, fetchConfig, fetchStatus, fetchRuns, fetchBlockingPR, clearSelection]);

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

  // When a DAG node's "Edit" prompt button is clicked, switch to prompts tab
  useSafeEffect('edit-prompt-redirect', () => {
    if (editPromptStageKey) {
      setInitialStageKey(editPromptStageKey);
      setActiveTab('prompts');
      setEditPromptStageKey(null);
    }
  }, [editPromptStageKey, setEditPromptStageKey]);

  const handleRepair = async () => {
    if (!projectId || repairing) return;
    setRepairing(true);
    setRepairResult(null);
    try {
      const result = await reconcilePipeline(projectId);
      const fixes = result.corrections.length + result.orphans_removed.length;
      setRepairResult(fixes > 0 ? `Fixed ${fixes} issue${fixes > 1 ? 's' : ''}` : 'No issues found');
      if (fixes > 0) {
        fetchStatus(projectId);
        fetchRuns(projectId);
      }
    } catch {
      setRepairResult('Repair failed');
    } finally {
      setRepairing(false);
      setTimeout(() => setRepairResult(null), 4000);
    }
  };

  if (!projectId) return null;

  // Prefer an awaiting_review execution so the approve button shows when the
  // artifact is in review.  Multiple executions can exist for the same artifact
  // across pipeline runs; without this preference, find() may return an older
  // approved/rejected one, hiding the review panel.
  //
  // Also match by component_key for stuck/failed executions whose artifact_id
  // is null (e.g., generation died before creating the artifact record), or
  // when the artifact_id doesn't match due to regeneration edge cases.
  // Input docs (project_doc) have no StageExecution — skip component_key
  // fallbacks for them to avoid matching unrelated executions.
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
      // Fallback: match by component_key when artifact_id is set but doesn't match
      // (can happen after regeneration creates a new execution with a stale artifact_id reference)
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
    errors: 'Error Log',
  };
  const visibleTabs: Tab[] = isViewer
    ? ['documents', 'pipeline', 'chat']
    : ['documents', 'pipeline', 'prompts', 'input-docs', 'chat', 'settings', 'history'];

  return (
    <div className="h-screen flex flex-col bg-gray-900 text-white">
      {/* Header — hidden on mobile when artifact pane is expanded */}
      <header className={`border-b border-gray-700 px-3 md:px-4 py-2 md:py-3 flex flex-wrap items-center justify-between gap-2 shrink-0 ${paneExpanded ? 'hidden md:flex' : ''}`}>
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
            onClick={() => { setActiveTab('debug'); clearSelection(); setMenuOpen(false); }}
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
          <button
            onClick={() => { setActiveTab('errors'); clearSelection(); setMenuOpen(false); }}
            className={`px-2 py-1 text-xs rounded min-h-[44px] md:min-h-0 relative ${
              activeTab === 'errors'
                ? 'bg-red-600 text-white'
                : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
            }`}
            title="Error Log"
          >
            <svg className="w-4 h-4 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            {errorCount > 0 && (
              <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] rounded-full w-4 h-4 flex items-center justify-center">
                {errorCount > 9 ? '9+' : errorCount}
              </span>
            )}
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

      {/* Navigation menu — hamburger with vertical dropdown */}
      <div className={`border-b border-gray-700 px-4 shrink-0 relative ${paneExpanded ? 'hidden md:block' : ''}`} ref={menuRef}>
        <button
          onClick={() => setMenuOpen(!menuOpen)}
          className="flex items-center gap-2 py-2 text-sm text-gray-300 hover:text-white min-h-[44px]"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
          <span>{tabLabels[activeTab]}</span>
        </button>
        {menuOpen && (
          <div className="absolute left-0 top-full z-50 w-48 bg-gray-800 border border-gray-700 rounded-b-lg shadow-xl">
            {visibleTabs.map((tab) => (
              <button
                key={tab}
                onClick={() => { setActiveTab(tab); clearSelection(); setMenuOpen(false); }}
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

      {/* Main content */}
      {activeTab === 'documents' || activeTab === 'pipeline' ? (
        <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
          {!paneExpanded && (
            <div className="h-64 md:h-auto md:w-3/5 border-b md:border-b-0 md:border-r border-gray-700 shrink-0 md:shrink">
              <PanelErrorBoundary fallbackLabel="DAG render error">
                {/* TEMP: commented out to isolate crash source */}
                {/* <PipelineDAG projectId={projectId} variant={activeTab === 'documents' ? 'documents' : 'pipeline'} /> */}
                <div className="flex items-center justify-center h-full text-gray-500">DAG disabled for debugging</div>
              </PanelErrorBoundary>
            </div>
          )}
          <div className={`flex-1 ${paneExpanded ? 'w-full' : 'md:w-2/5'} flex flex-col overflow-hidden`}>
            {selectedArtifact ? (
              <div className="flex-1 flex flex-col overflow-hidden">
                <div className="flex items-center justify-end px-3 py-1 border-b border-gray-700 shrink-0">
                  <button
                    onClick={() => setPaneExpanded(!paneExpanded)}
                    className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 hover:text-white text-xs rounded"
                    title={paneExpanded ? 'Collapse pane' : 'Expand to full width'}
                  >
                    {paneExpanded ? '⇥ Collapse' : '⇤ Expand'}
                  </button>
                </div>
                {paneExpanded && (
                  (selectedExecution && ['awaiting_review', 'running', 'ai_review', 'failed'].includes(selectedExecution.status))
                  || selectedArtifact.status === 'stale'
                ) ? (
                  <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
                    <div className="flex-1 md:w-2/3 overflow-auto border-b md:border-b-0 md:border-r border-gray-700">
                      <PanelErrorBoundary fallbackLabel="Editor error">
                        <ArtifactEditor key={selectedArtifact.id} artifact={selectedArtifact} projectId={projectId} />
                      </PanelErrorBoundary>
                    </div>
                    <div className="md:w-1/3 overflow-auto p-3">
                      <PanelErrorBoundary fallbackLabel="Review panel error">
                        <ReviewPanel
                          projectId={projectId}
                          artifact={selectedArtifact}
                          execution={selectedExecution}
                        />
                      </PanelErrorBoundary>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex-1 overflow-auto">
                      <PanelErrorBoundary fallbackLabel="Editor error">
                        <ArtifactEditor key={selectedArtifact.id} artifact={selectedArtifact} projectId={projectId} />
                      </PanelErrorBoundary>
                    </div>
                    <div className="shrink-0 p-3 border-t border-gray-700 overflow-auto max-h-64">
                      <PanelErrorBoundary fallbackLabel="Review panel error">
                        <ReviewPanel
                          projectId={projectId}
                          artifact={selectedArtifact}
                          execution={selectedExecution}
                        />
                      </PanelErrorBoundary>
                    </div>
                  </>
                )}
              </div>
            ) : activeTab === 'pipeline' && selectedStageKey ? (
              <PanelErrorBoundary fallbackLabel="Stage config error">
                <StageConfigPanel projectId={projectId} stageKey={selectedStageKey} />
              </PanelErrorBoundary>
            ) : (
              <div className="flex-1 flex flex-col min-h-0">
                <div className="p-4 text-gray-500 text-sm shrink-0">
                  {activeTab === 'documents'
                    ? 'Select a document node to view, edit, or start a run'
                    : 'Select a stage node to configure it or start a run'}
                </div>
                {activeTab === 'pipeline' && (
                  <div className="flex-1 p-4 border-t border-gray-700 overflow-auto min-h-0">
                    <PanelErrorBoundary fallbackLabel="Stage status error">
                      <StageStatusList executions={executions} projectId={projectId} />
                    </PanelErrorBoundary>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      ) : activeTab === 'prompts' ? (
        <div className="flex-1 overflow-hidden">
          <PanelErrorBoundary fallbackLabel="Prompt editor error">
            <PromptEditorPanel
              projectId={projectId}
              initialStageKey={initialStageKey}
              onStageKeyConsumed={() => setInitialStageKey(null)}
            />
          </PanelErrorBoundary>
        </div>
      ) : activeTab === 'input-docs' ? (
        <div className="flex-1 overflow-hidden">
          <PanelErrorBoundary fallbackLabel="Input docs error">
            <InputDocsPanel projectId={projectId} />
          </PanelErrorBoundary>
        </div>
      ) : activeTab === 'chat' ? (
        <div className="flex-1 overflow-hidden">
          <PanelErrorBoundary fallbackLabel="Chat error">
            <ChatPanel projectId={projectId} />
          </PanelErrorBoundary>
        </div>
      ) : activeTab === 'history' ? (
        <div className="flex-1 overflow-hidden">
          <PanelErrorBoundary fallbackLabel="Event history error">
            <EventHistoryPanel projectId={projectId} />
          </PanelErrorBoundary>
        </div>
      ) : activeTab === 'logs' ? (
        <div className="flex-1 overflow-hidden">
          <PanelErrorBoundary fallbackLabel="Log panel error">
            <LogPanel />
          </PanelErrorBoundary>
        </div>
      ) : activeTab === 'debug' ? (
        <div className="flex-1 overflow-hidden">
          <PanelErrorBoundary fallbackLabel="Debug panel error">
            <DebugStatePanel projectId={projectId} />
          </PanelErrorBoundary>
        </div>
      ) : activeTab === 'errors' ? (
        <div className="flex-1 overflow-auto">
          <ErrorLogPanel />
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <PanelErrorBoundary fallbackLabel="Settings error">
            <ProjectSettingsPanel projectId={projectId} />
          </PanelErrorBoundary>
        </div>
      )}

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
