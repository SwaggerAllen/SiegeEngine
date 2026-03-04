import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useProjectStore } from '../store/projectStore';
import { usePipelineStore } from '../store/pipelineStore';
import { useAuthStore } from '../store/authStore';
import { useWebSocket } from '../hooks/useWebSocket';
import { PipelineDAG } from '../components/dag/PipelineDAG';
import { PipelineControls } from '../components/pipeline/PipelineControls';
import { StageStatusList } from '../components/pipeline/StageStatus';
import { ArtifactEditor } from '../components/editor/ArtifactEditor';
import { ReviewPanel } from '../components/pipeline/ReviewPanel';
import { InvitePanel } from '../components/auth/InvitePanel';
import { PromptEditorPanel } from '../components/pipeline/PromptEditorPanel';
import { ProjectSettingsPanel } from '../components/project/ProjectSettingsPanel';
import api from '../api/client';

type Tab = 'pipeline' | 'prompts' | 'settings';

export function ProjectDashboardPage() {
  const { id: projectId } = useParams<{ id: string }>();
  const { currentProject, fetchProject, selectedArtifact, clearSelection } =
    useProjectStore();
  const { executions, fetchConfig, fetchStatus } = usePipelineStore();
  const { user } = useAuthStore();
  const { connected } = useWebSocket(projectId);
  const [showInvites, setShowInvites] = useState(false);
  const [showPRDialog, setShowPRDialog] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>('pipeline');

  useEffect(() => {
    if (projectId) {
      fetchProject(projectId);
      fetchConfig(projectId);
      fetchStatus(projectId);
    }
    return () => clearSelection();
  }, [projectId]);

  if (!projectId) return null;

  const selectedExecution = selectedArtifact
    ? executions.find((e) => e.artifact_id === selectedArtifact.id)
    : undefined;

  const isAdmin = user?.role === 'admin';
  const hasRemote = !!currentProject?.remote_url;

  return (
    <div className="h-screen flex flex-col bg-gray-900 text-white">
      {/* Header */}
      <header className="border-b border-gray-700 px-4 py-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-4">
          <Link to="/projects" className="text-gray-400 hover:text-white text-sm">
            &larr; Projects
          </Link>
          <h1 className="text-lg font-bold">
            {currentProject?.name || 'Loading...'}
          </h1>
        </div>
        <div className="flex items-center gap-4">
          <PipelineControls projectId={projectId} />
          {hasRemote && (
            <button
              onClick={() => setShowPRDialog(true)}
              className="px-2 py-1 bg-purple-600 hover:bg-purple-700 text-white text-xs rounded"
            >
              Open PR
            </button>
          )}
          {isAdmin && (
            <button
              onClick={() => setShowInvites(true)}
              className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded"
            >
              Invites
            </button>
          )}
          <span
            className={`text-xs ${connected ? 'text-green-400' : 'text-red-400'}`}
          >
            {connected ? 'WS Connected' : 'WS Disconnected'}
          </span>
        </div>
      </header>

      {/* Tab bar */}
      <div className="border-b border-gray-700 px-4 flex gap-4 shrink-0">
        {(['pipeline', 'prompts', 'settings'] as Tab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`py-2 text-sm border-b-2 capitalize ${
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
      {activeTab === 'pipeline' ? (
        <div className="flex-1 flex overflow-hidden">
          <div className="w-3/5 border-r border-gray-700">
            <PipelineDAG projectId={projectId} />
          </div>
          <div className="w-2/5 flex flex-col overflow-hidden">
            {selectedArtifact ? (
              <div className="flex-1 flex flex-col overflow-hidden">
                <div className="flex-1 overflow-auto">
                  <ArtifactEditor artifact={selectedArtifact} />
                </div>
                <div className="shrink-0 p-3 border-t border-gray-700 overflow-auto max-h-64">
                  <ReviewPanel
                    projectId={projectId}
                    artifact={selectedArtifact}
                    execution={selectedExecution}
                  />
                </div>
              </div>
            ) : (
              <div className="flex-1 flex flex-col">
                <div className="p-4 text-gray-500 text-sm">
                  Select an artifact node in the DAG to view details
                </div>
                <div className="p-4 border-t border-gray-700 overflow-auto">
                  <StageStatusList executions={executions} />
                </div>
              </div>
            )}
          </div>
        </div>
      ) : activeTab === 'prompts' ? (
        <div className="flex-1 overflow-hidden">
          <PromptEditorPanel projectId={projectId} />
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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-white">Open Pull Request</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">
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
