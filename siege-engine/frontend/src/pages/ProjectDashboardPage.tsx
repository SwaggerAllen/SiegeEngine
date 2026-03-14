import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useProjectStore } from '../store/projectStore';
import { usePipelineStore } from '../store/pipelineStore';
import { useAuthStore } from '../store/authStore';
import { useDAGStore } from '../store/dagStore';
import { useWebSocket } from '../hooks/useWebSocket';
import { useVisibilityRefresh } from '../hooks/useVisibilityRefresh';
import { PipelineDAG } from '../components/dag/PipelineDAG';
import { PipelineControls } from '../components/pipeline/PipelineControls';
import { StageStatusList } from '../components/pipeline/StageStatus';
import { ArtifactEditor } from '../components/editor/ArtifactEditor';
import { ReviewPanel } from '../components/pipeline/ReviewPanel';
import { InvitePanel } from '../components/auth/InvitePanel';
import { PromptEditorPanel } from '../components/pipeline/PromptEditorPanel';
import { StageConfigPanel } from '../components/pipeline/StageConfigPanel';
import { ProjectSettingsPanel } from '../components/project/ProjectSettingsPanel';
import { ChatPanel } from '../components/chat/ChatPanel';
import { RunSelector } from '../components/pipeline/RunSelector';
import api from '../api/client';

type Tab = 'documents' | 'pipeline' | 'prompts' | 'chat' | 'settings';

export function ProjectDashboardPage() {
  const { id: projectId } = useParams<{ id: string }>();
  const { currentProject, fetchProject, selectedArtifact, clearSelection } =
    useProjectStore();
  const { executions, fetchConfig, fetchStatus, fetchRuns, currentRunNumber, isRunning, isViewingHistory, reset: resetPipeline } = usePipelineStore();
  const { user } = useAuthStore();
  const { editPromptStageKey, setEditPromptStageKey, selectedStageKey } = useDAGStore();
  const { connected, reconnect } = useWebSocket(projectId);
  useVisibilityRefresh(projectId, reconnect);
  const [showInvites, setShowInvites] = useState(false);
  const [showPRDialog, setShowPRDialog] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>('documents');
  const [paneExpanded, setPaneExpanded] = useState(false);
  const [initialStageKey, setInitialStageKey] = useState<string | null>(null);

  useEffect(() => {
    resetPipeline();
    if (projectId) {
      fetchProject(projectId);
      fetchConfig(projectId);
      fetchStatus(projectId);
      fetchRuns(projectId);
    }
    return () => clearSelection();
  }, [projectId]);

  // When a DAG node's "Edit" prompt button is clicked, switch to prompts tab
  useEffect(() => {
    if (editPromptStageKey) {
      setInitialStageKey(editPromptStageKey);
      setActiveTab('prompts');
      setEditPromptStageKey(null);
    }
  }, [editPromptStageKey]);

  if (!projectId) return null;

  // Prefer an awaiting_review execution so the approve button shows when the
  // artifact is in review.  Multiple executions can exist for the same artifact
  // across pipeline runs; without this preference, find() may return an older
  // approved/rejected one, hiding the review panel.
  const selectedExecution = selectedArtifact
    ? executions.find((e) => e.artifact_id === selectedArtifact.id && e.status === 'awaiting_review')
      || executions.find((e) => e.artifact_id === selectedArtifact.id)
    : undefined;

  const isAdmin = user?.role === 'admin';
  const isViewer = user?.role === 'viewer';
  const hasRemote = !!currentProject?.remote_url;
  const visibleTabs: Tab[] = isViewer
    ? ['documents', 'pipeline', 'chat']
    : ['documents', 'pipeline', 'prompts', 'chat', 'settings'];

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
          {!isViewer && !isViewingHistory && <PipelineControls projectId={projectId} />}
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

      {/* Tab bar — hidden on mobile when artifact pane is expanded */}
      <div className={`border-b border-gray-700 px-4 flex gap-4 shrink-0 ${paneExpanded ? 'hidden md:flex' : ''}`}>
        {visibleTabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`py-2 text-sm border-b-2 capitalize min-h-[44px] md:min-h-0 ${
              activeTab === tab
                ? 'border-blue-500 text-white'
                : 'border-transparent text-gray-400 hover:text-white'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Main content */}
      {activeTab === 'documents' || activeTab === 'pipeline' ? (
        <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
          {!paneExpanded && (
            <div className="h-64 md:h-auto md:w-3/5 border-b md:border-b-0 md:border-r border-gray-700 shrink-0 md:shrink">
              <PipelineDAG projectId={projectId} variant={activeTab === 'documents' ? 'documents' : 'pipeline'} />
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
                {paneExpanded && selectedExecution?.status === 'awaiting_review' ? (
                  <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
                    <div className="flex-1 md:w-2/3 overflow-auto border-b md:border-b-0 md:border-r border-gray-700">
                      <ArtifactEditor artifact={selectedArtifact} projectId={projectId} />
                    </div>
                    <div className="md:w-1/3 overflow-auto p-3">
                      <ReviewPanel
                        projectId={projectId}
                        artifact={selectedArtifact}
                        execution={selectedExecution}
                      />
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex-1 overflow-auto">
                      <ArtifactEditor artifact={selectedArtifact} projectId={projectId} />
                    </div>
                    <div className="shrink-0 p-3 border-t border-gray-700 overflow-auto max-h-64">
                      <ReviewPanel
                        projectId={projectId}
                        artifact={selectedArtifact}
                        execution={selectedExecution}
                      />
                    </div>
                  </>
                )}
              </div>
            ) : activeTab === 'pipeline' && selectedStageKey ? (
              <StageConfigPanel projectId={projectId} stageKey={selectedStageKey} />
            ) : (
              <div className="flex-1 flex flex-col">
                <div className="p-4 text-gray-500 text-sm">
                  {activeTab === 'documents'
                    ? 'Select a document node to view or edit'
                    : 'Select a stage node to configure it'}
                </div>
                {activeTab === 'pipeline' && (
                  <div className="p-4 border-t border-gray-700 overflow-auto">
                    <StageStatusList executions={executions} />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      ) : activeTab === 'prompts' ? (
        <div className="flex-1 overflow-hidden">
          <PromptEditorPanel
            projectId={projectId}
            initialStageKey={initialStageKey}
            onStageKeyConsumed={() => setInitialStageKey(null)}
          />
        </div>
      ) : activeTab === 'chat' ? (
        <div className="flex-1 overflow-hidden">
          <ChatPanel projectId={projectId} />
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <ProjectSettingsPanel projectId={projectId} />
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
    } catch (err: any) {
      setResult({ error: err.response?.data?.detail || 'Failed to create PR' });
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
