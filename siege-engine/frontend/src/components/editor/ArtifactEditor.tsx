import { useEffect, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import { useProjectStore } from '../../store/projectStore';
import { useAuthStore } from '../../store/authStore';
import { useReviseArtifact } from '../../hooks/mutations/usePipelineMutations';
import { formatDateTime } from '../../utils/dateFormat';
import { getArtifactHistory, getArtifactVersion } from '../../api/projects';
import { getPromptPreview } from '../../api/pipeline';
import { useLocalDraft } from '../../hooks/useLocalDraft';
import type { ArtifactVersion } from '../../api/projects';
import type { PromptPreview } from '../../api/pipeline';
import type { Artifact } from '../../types/project';
import { CommentsPanel } from '../comments/CommentsPanel';
import { ComponentDependencyList } from './ComponentDependencyList';
import DiffView from './DiffView';

const REVISABLE_STATUSES = new Set(['approved', 'stale']);

type EditorTab = 'document' | 'diff' | 'feedback' | 'comments' | 'prompt' | 'dependencies';

export function ArtifactEditor({ artifact, projectId }: { artifact: Artifact; projectId: string }) {
  const updateArtifact = useProjectStore((s) => s.updateArtifact);
  const reviseArtifactMutation = useReviseArtifact(projectId);
  const { user } = useAuthStore();
  const isViewer = user?.role === 'viewer';
  const [editing, setEditing] = useState(false);
  const [content, setContent, clearContent] = useLocalDraft(`editor-content:${artifact.id}`, artifact.content || '');
  const [saving, setSaving] = useState(false);
  const [showRevise, setShowRevise] = useState(false);
  const [feedback, setFeedback, clearFeedback] = useLocalDraft(`revision-request:${artifact.id}`);
  const [submittingRevision, setSubmittingRevision] = useState(false);
  const [activeTab, setActiveTab] = useState<EditorTab>('document');
  const [history, setHistory] = useState<ArtifactVersion[]>([]);
  const [viewingSha, setViewingSha] = useState<string | null>(null);
  const [historicalContent, setHistoricalContent] = useState<string | null>(null);
  const [loadingVersion, setLoadingVersion] = useState(false);
  const [restoringVersion, setRestoringVersion] = useState(false);
  const [promptPreview, setPromptPreview] = useState<PromptPreview | null>(null);
  const [loadingPrompt, setLoadingPrompt] = useState(false);

  interface ReviewIssue {
    severity: string;
    description: string;
  }
  interface ReviewFeedback {
    overall_quality?: string;
    recommendation?: string;
    document?: unknown;
    issues?: ReviewIssue[];
  }

  const canRevise = !isViewer && REVISABLE_STATUSES.has(artifact.status);
  const reviewFeedback = artifact.ai_review_feedback as ReviewFeedback | null;
  const isViewingHistory = viewingSha !== null;
  const isComponentMap = artifact.artifact_type === 'component_map';

  // Reset tab when artifact changes and feedback is gone
  useEffect(() => {
    if (!reviewFeedback && activeTab === 'feedback') {
      setActiveTab('document');
    }
    setPromptPreview(null);
  }, [artifact.id, reviewFeedback, activeTab]);

  // Track previous artifact to distinguish "switched artifact" from "version bumped"
  const prevArtifactRef = useRef({ id: artifact.id, version: artifact.version });
  useEffect(() => {
    const prev = prevArtifactRef.current;
    prevArtifactRef.current = { id: artifact.id, version: artifact.version };

    if (prev.id !== artifact.id) {
      // Switched to a different artifact — just reset UI state, keep drafts
      setEditing(false);
      setShowRevise(false);
      return;
    }

    if (prev.version !== artifact.version) {
      // Same artifact, version bumped (AI revision / restore) — clear drafts
      clearContent();
      setContent(artifact.content || '');
      setEditing(false);
      setShowRevise(false);
      clearFeedback();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifact.id, artifact.version]);

  // Fetch prompt preview when tab is selected
  useEffect(() => {
    if (activeTab !== 'prompt') return;
    if (promptPreview) return; // already loaded for this artifact
    setLoadingPrompt(true);
    getPromptPreview(projectId, artifact.id)
      .then(setPromptPreview)
      .catch((err) => console.error('Prompt preview failed:', err))
      .finally(() => setLoadingPrompt(false));
  }, [activeTab, projectId, artifact.id, promptPreview]);

  // Fetch version history when artifact changes
  useEffect(() => {
    setViewingSha(null);
    setHistoricalContent(null);
    if (artifact.file_path) {
      getArtifactHistory(artifact.id)
        .then(setHistory)
        .catch(() => setHistory([]));
    } else {
      setHistory([]);
    }
  }, [artifact.id, artifact.version, artifact.file_path]);

  // Parse version number from commit message (e.g. "Generate System Requirements v3" → 3)
  const parseVersion = (message: string): string | null => {
    const match = message.match(/v(\d+)/i);
    return match ? match[1] : null;
  };

  // Format timestamp for display
  const formatDate = (ts: string): string => formatDateTime(ts);

  const handleVersionChange = async (sha: string) => {
    if (!sha) {
      // Back to current
      setViewingSha(null);
      setHistoricalContent(null);
      return;
    }
    setLoadingVersion(true);
    try {
      const result = await getArtifactVersion(artifact.id, sha);
      setViewingSha(sha);
      setHistoricalContent(result.content);
    } catch (err) {
      console.error('Failed to load version:', err);
    } finally {
      setLoadingVersion(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateArtifact(artifact.id, content);
      clearContent();
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const handleRevise = async () => {
    if (!feedback.trim()) return;
    setSubmittingRevision(true);
    try {
      await reviseArtifactMutation.mutateAsync({ artifactId: artifact.id, feedback });
      clearFeedback();
      setShowRevise(false);
    } finally {
      setSubmittingRevision(false);
    }
  };

  const handleRestore = async () => {
    if (!historicalContent) return;
    setRestoringVersion(true);
    try {
      await updateArtifact(artifact.id, historicalContent);
      setViewingSha(null);
      setHistoricalContent(null);
    } finally {
      setRestoringVersion(false);
    }
  };

  const proseClasses = `flex-1 p-3 md:p-4 overflow-auto prose prose-invert prose-sm max-w-none
    prose-headings:text-gray-100
    prose-h2:text-lg prose-h2:font-bold prose-h2:mt-8 prose-h2:mb-3 prose-h2:border-b prose-h2:border-gray-700 prose-h2:pb-2
    prose-h3:text-base prose-h3:font-semibold prose-h3:mt-6 prose-h3:mb-2
    prose-p:text-gray-300 prose-p:my-3 prose-p:leading-relaxed
    prose-li:text-gray-300
    prose-strong:text-white prose-code:text-blue-300 prose-code:bg-gray-800
    prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none
    prose-code:after:content-none prose-pre:bg-gray-800 prose-pre:border prose-pre:border-gray-700
    prose-a:text-blue-400 prose-blockquote:border-gray-600 prose-blockquote:text-gray-400
    prose-hr:border-gray-700 prose-th:text-gray-200 prose-td:text-gray-300`;

  return (
    <div className="h-full flex flex-col min-w-0 max-w-full overflow-x-hidden">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between px-3 py-2 border-b border-gray-700 gap-2">
        <div className="min-w-0 flex items-center gap-2">
          <span className="text-sm font-medium text-white truncate">{artifact.name}</span>
          {history.length > 1 ? (
            <select
              value={viewingSha || ''}
              onChange={(e) => handleVersionChange(e.target.value)}
              disabled={loadingVersion}
              className="text-xs bg-gray-700 text-gray-200 border border-gray-600 rounded px-1.5 py-0.5 focus:outline-none focus:border-blue-500 disabled:opacity-50 cursor-pointer"
            >
              <option value="">v{artifact.version} (current)</option>
              {history.map((entry) => {
                const vNum = parseVersion(entry.message);
                const label = vNum
                  ? `v${vNum} — ${formatDate(entry.timestamp)}`
                  : `${formatDate(entry.timestamp)}`;
                // Skip the first entry if it matches current version's SHA
                if (entry.sha === artifact.git_commit_sha) return null;
                return (
                  <option key={entry.sha} value={entry.sha}>
                    {label}
                  </option>
                );
              })}
            </select>
          ) : (
            <span className="text-xs text-gray-400">v{artifact.version}</span>
          )}
          <span
            className={`text-xs px-1.5 py-0.5 rounded ${
              artifact.status === 'approved'
                ? 'bg-green-900 text-green-300'
                : artifact.status === 'stale'
                ? 'bg-orange-900 text-orange-300'
                : artifact.status === 'awaiting_review'
                ? 'bg-yellow-900 text-yellow-300'
                : 'bg-gray-700 text-gray-300'
            }`}
          >
            {artifact.status}
          </span>
        </div>
        {!isViewer && !isViewingHistory && (
          <div className="flex gap-2">
            {editing ? (
              <>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="px-2 py-1 bg-green-600 hover:bg-green-700 text-white text-xs rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
                <button
                  onClick={() => {
                    clearContent();
                    setContent(artifact.content || '');
                    setEditing(false);
                  }}
                  className="px-2 py-1 bg-gray-600 hover:bg-gray-500 text-white text-xs rounded min-h-[44px] md:min-h-0"
                >
                  Cancel
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={() => setEditing(true)}
                  className="px-2 py-1 bg-gray-600 hover:bg-gray-500 text-white text-xs rounded min-h-[44px] md:min-h-0"
                >
                  Edit
                </button>
                {canRevise && (
                  <button
                    onClick={() => setShowRevise(!showRevise)}
                    className={`px-2 py-1 text-xs rounded min-h-[44px] md:min-h-0 ${
                      showRevise
                        ? 'bg-blue-600 hover:bg-blue-700 text-white'
                        : 'bg-gray-600 hover:bg-gray-500 text-white'
                    }`}
                  >
                    {showRevise ? 'Cancel Revision' : 'Request AI Revision'}
                  </button>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* Tab bar */}
      <div className="border-b border-gray-700 px-3 flex gap-4 shrink-0">
        <button
          onClick={() => setActiveTab('document')}
          className={`py-1.5 text-xs border-b-2 min-h-[44px] md:min-h-0 ${
            activeTab === 'document'
              ? 'border-blue-500 text-white'
              : 'border-transparent text-gray-400 hover:text-white'
          }`}
        >
          Document
        </button>
        {artifact.version > 1 && (
          <button
            onClick={() => setActiveTab('diff')}
            className={`py-1.5 text-xs border-b-2 min-h-[44px] md:min-h-0 ${
              activeTab === 'diff'
                ? 'border-yellow-500 text-white'
                : 'border-transparent text-gray-400 hover:text-white'
            }`}
          >
            Diff
          </button>
        )}
        {!isViewer && reviewFeedback && (
          <button
            onClick={() => setActiveTab('feedback')}
            className={`py-1.5 text-xs border-b-2 min-h-[44px] md:min-h-0 ${
              activeTab === 'feedback'
                ? 'border-blue-500 text-white'
                : 'border-transparent text-gray-400 hover:text-white'
            }`}
          >
            AI Feedback
          </button>
        )}
        <button
          onClick={() => setActiveTab('comments')}
          className={`py-1.5 text-xs border-b-2 min-h-[44px] md:min-h-0 ${
            activeTab === 'comments'
              ? 'border-blue-500 text-white'
              : 'border-transparent text-gray-400 hover:text-white'
          }`}
        >
          Comments
        </button>
        {isComponentMap && (
          <button
            onClick={() => setActiveTab('dependencies')}
            className={`py-1.5 text-xs border-b-2 min-h-[44px] md:min-h-0 ${
              activeTab === 'dependencies'
                ? 'border-indigo-500 text-white'
                : 'border-transparent text-gray-400 hover:text-white'
            }`}
          >
            Dependencies
          </button>
        )}
        {!isViewer && (
          <button
            onClick={() => setActiveTab('prompt')}
            className={`py-1.5 text-xs border-b-2 min-h-[44px] md:min-h-0 ${
              activeTab === 'prompt'
                ? 'border-purple-500 text-white'
                : 'border-transparent text-gray-400 hover:text-white'
            }`}
          >
            Prompt Preview
          </button>
        )}
      </div>

      {/* Revision request section - only on document tab, not while viewing history */}
      {showRevise && activeTab === 'document' && !isViewingHistory && (
        <div className="px-3 py-2 border-b border-gray-700 bg-gray-800/50 space-y-2">
          <label className="block text-xs text-gray-400">
            Describe what changes you want the AI to make:
          </label>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            className="w-full h-24 px-2 py-1 bg-gray-800 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
            placeholder="e.g. Add more detail about error handling, restructure the data flow section..."
          />
          <div className="flex gap-2">
            <button
              onClick={handleRevise}
              disabled={submittingRevision || !feedback.trim()}
              className="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
            >
              {submittingRevision ? 'Submitting...' : 'Submit for AI Revision'}
            </button>
          </div>
        </div>
      )}

      {/* Historical version banner */}
      {isViewingHistory && activeTab === 'document' && (
        <div className="flex items-center gap-3 px-3 py-2 bg-amber-900/30 border-b border-amber-700/50">
          <svg className="w-4 h-4 text-amber-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span className="text-xs text-amber-300">
            Viewing historical version
            {(() => {
              const entry = history.find((h) => h.sha === viewingSha);
              if (!entry) return '';
              const vNum = parseVersion(entry.message);
              return vNum ? ` (v${vNum})` : '';
            })()}
            {' — read only'}
          </span>
          <div className="ml-auto flex items-center gap-3">
            {!isViewer && (
              <button
                onClick={handleRestore}
                disabled={restoringVersion}
                className="text-xs px-2 py-1 bg-amber-600 hover:bg-amber-700 text-white rounded disabled:opacity-50"
              >
                {restoringVersion ? 'Restoring...' : 'Restore this version'}
              </button>
            )}
            <button
              onClick={() => handleVersionChange('')}
              className="text-xs text-amber-400 hover:text-amber-200 underline"
            >
              Back to current
            </button>
          </div>
        </div>
      )}

      {/* Content area */}
      {activeTab === 'document' ? (
        <>
          {isViewingHistory ? (
            <div className={proseClasses}>
              <Markdown>{historicalContent || 'Loading...'}</Markdown>
            </div>
          ) : editing ? (
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="flex-1 w-full p-3 bg-gray-900 text-white font-mono text-sm resize-none focus:outline-none"
            />
          ) : (
            <div className={proseClasses}>
              <Markdown>{artifact.content || 'No content'}</Markdown>
            </div>
          )}
        </>
      ) : activeTab === 'feedback' ? (
        /* AI Feedback tab: summary + full document */
        <div className="flex-1 overflow-auto">
          {/* AI Review summary */}
          {reviewFeedback && (
            <div className="mx-3 mt-3 bg-gray-800 p-3 rounded text-sm">
              <div className="flex items-center gap-3">
                <span className="text-gray-400">Quality:</span>
                <span className="text-white font-medium">{reviewFeedback.overall_quality}/10</span>
                <span className="text-gray-400 ml-2">Recommendation:</span>
                <span
                  className={`font-medium ${
                    reviewFeedback.recommendation === 'approve'
                      ? 'text-green-400'
                      : 'text-yellow-400'
                  }`}
                >
                  {reviewFeedback.recommendation}
                </span>
              </div>
              {/* Backward compatibility: show old-format issues if present */}
              {!reviewFeedback.document && Array.isArray(reviewFeedback.issues) && reviewFeedback.issues.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {reviewFeedback.issues.map((issue: ReviewIssue, i: number) => (
                    <li key={i} className="text-gray-300 text-xs">
                      <span
                        className={`font-medium ${
                          issue.severity === 'high'
                            ? 'text-red-400'
                            : issue.severity === 'medium'
                            ? 'text-yellow-400'
                            : 'text-green-400'
                        }`}
                      >
                        [{issue.severity}]
                      </span>{' '}
                      {issue.description}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {/* Full review document */}
          <div className={proseClasses}>
            <Markdown>
              {(typeof reviewFeedback?.document === 'string' ? reviewFeedback.document : '') || 'No feedback available'}
            </Markdown>
          </div>
        </div>
      ) : activeTab === 'diff' ? (
        <DiffView projectId={projectId} artifactId={artifact.id} artifactVersion={artifact.version} />
      ) : activeTab === 'prompt' ? (
        /* Prompt Preview tab */
        <div className="flex-1 overflow-auto p-3 space-y-3">
          {loadingPrompt ? (
            <div className="text-sm text-gray-400">Loading prompt preview...</div>
          ) : promptPreview ? (
            <PromptPreviewPanel preview={promptPreview} />
          ) : (
            <div className="text-sm text-gray-400">No prompt preview available.</div>
          )}
        </div>
      ) : activeTab === 'dependencies' ? (
        <ComponentDependencyList projectId={projectId} refreshKey={artifact.version} />
      ) : (
        /* Comments tab */
        <CommentsPanel projectId={projectId} artifactId={artifact.id} />
      )}
    </div>
  );
}

function PromptPreviewPanel({ preview }: { preview: PromptPreview }) {
  const roleColors: Record<string, string> = {
    system: 'text-purple-400 bg-purple-950/30 border-purple-700/40',
    user: 'text-blue-400 bg-blue-950/30 border-blue-700/40',
    assistant: 'text-green-400 bg-green-950/30 border-green-700/40',
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold text-purple-400 uppercase tracking-wide">
          Prompt Preview
        </h4>
        <span className="text-xs text-gray-500">
          {preview.model} &middot; temp {preview.temperature}
        </span>
      </div>
      {preview.messages.map((msg, i) => (
        <div
          key={i}
          className={`rounded border p-2 ${roleColors[msg.role] || 'text-gray-300 bg-gray-800 border-gray-600'}`}
        >
          <div className="text-xs font-semibold uppercase mb-1 opacity-70">
            {msg.role}
          </div>
          <pre className="text-xs whitespace-pre-wrap break-words font-mono leading-relaxed max-h-64 overflow-auto">
            {msg.content}
          </pre>
        </div>
      ))}
    </div>
  );
}
