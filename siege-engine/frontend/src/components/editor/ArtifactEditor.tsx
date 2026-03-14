import { useEffect, useState } from 'react';
import Markdown from 'react-markdown';
import { useProjectStore } from '../../store/projectStore';
import { usePipelineStore } from '../../store/pipelineStore';
import { useAuthStore } from '../../store/authStore';
import type { Artifact } from '../../types/project';
import { CommentsPanel } from '../comments/CommentsPanel';

const REVISABLE_STATUSES = new Set(['approved', 'stale']);

type EditorTab = 'document' | 'feedback' | 'comments';

export function ArtifactEditor({ artifact, projectId }: { artifact: Artifact; projectId: string }) {
  const { updateArtifact } = useProjectStore();
  const { reviseArtifact } = usePipelineStore();
  const { user } = useAuthStore();
  const isViewer = user?.role === 'viewer';
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(artifact.content || '');
  const [saving, setSaving] = useState(false);
  const [showRevise, setShowRevise] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [submittingRevision, setSubmittingRevision] = useState(false);
  const [activeTab, setActiveTab] = useState<EditorTab>('document');

  const canRevise = !isViewer && REVISABLE_STATUSES.has(artifact.status);
  const reviewFeedback = artifact.ai_review_feedback as any;

  // Reset tab when artifact changes and feedback is gone
  useEffect(() => {
    if (!reviewFeedback && activeTab === 'feedback') {
      setActiveTab('document');
    }
  }, [artifact.id, reviewFeedback]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateArtifact(artifact.id, content);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const handleRevise = async () => {
    if (!feedback.trim()) return;
    setSubmittingRevision(true);
    try {
      await reviseArtifact(projectId, artifact.id, feedback);
      setFeedback('');
      setShowRevise(false);
    } finally {
      setSubmittingRevision(false);
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
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between px-3 py-2 border-b border-gray-700 gap-2">
        <div className="min-w-0">
          <span className="text-sm font-medium text-white truncate">{artifact.name}</span>
          <span className="text-xs text-gray-400 ml-2">v{artifact.version}</span>
          <span
            className={`text-xs ml-2 px-1.5 py-0.5 rounded ${
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
        {!isViewer && (
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
      </div>

      {/* Revision request section - only on document tab */}
      {showRevise && activeTab === 'document' && (
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

      {/* Content area */}
      {activeTab === 'document' ? (
        <>
          {editing ? (
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
              {!reviewFeedback.document && reviewFeedback.issues?.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {reviewFeedback.issues.map((issue: any, i: number) => (
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
              {reviewFeedback?.document || 'No feedback available'}
            </Markdown>
          </div>
        </div>
      ) : (
        /* Comments tab */
        <CommentsPanel projectId={projectId} artifactId={artifact.id} />
      )}
    </div>
  );
}
