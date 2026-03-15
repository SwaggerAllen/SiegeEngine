import { useState, useEffect } from 'react';
import { usePipelineStore } from '../../store/pipelineStore';
import { useAuthStore } from '../../store/authStore';
import { listComments } from '../../api/comments';
import { getPromptPreview } from '../../api/pipeline';
import type { PromptPreview } from '../../api/pipeline';
import { CommentsPanel } from '../comments/CommentsPanel';
import type { Artifact } from '../../types/project';
import type { StageExecution } from '../../types/pipeline';

interface ReviewPanelProps {
  projectId: string;
  artifact: Artifact;
  execution: StageExecution | undefined;
}

export function ReviewPanel({ projectId, artifact, execution }: ReviewPanelProps) {
  const { resumeStage } = usePipelineStore();
  const { user } = useAuthStore();
  const isViewer = user?.role === 'viewer';
  const [notes, setNotes] = useState('');
  const [editedContent, setEditedContent] = useState('');
  const [showEditor, setShowEditor] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedbackSaved, setFeedbackSaved] = useState(false);
  const [feedbackCount, setFeedbackCount] = useState(0);
  const [promptPreview, setPromptPreview] = useState<PromptPreview | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  const isAwaitingReview = execution?.status === 'awaiting_review';

  // Reset to blank when switching artifacts; fetch feedback count
  useEffect(() => {
    setNotes('');
    setFeedbackSaved(false);
    setPromptPreview(null);
    setShowPreview(false);
    // Count existing feedback entries for this artifact
    listComments(projectId, artifact.id).then((comments) => {
      setFeedbackCount(comments.filter((c) => c.comment_type === 'feedback').length);
    }).catch(() => {});
  }, [projectId, artifact.id]);

  const handleAction = async (action: string) => {
    if (!execution) return;
    setSubmitting(true);
    try {
      await resumeStage(
        projectId,
        execution.id,
        action,
        notes || undefined,
        showEditor && editedContent ? editedContent : undefined
      );
      if (action === 'save_feedback') {
        setFeedbackSaved(true);
        setFeedbackCount((c) => c + 1);
      } else {
        setNotes('');
        setEditedContent('');
        setShowEditor(false);
        setFeedbackSaved(false);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handlePreviewPrompt = async () => {
    if (showPreview && promptPreview) {
      setShowPreview(false);
      return;
    }
    setLoadingPreview(true);
    try {
      const preview = await getPromptPreview(
        projectId,
        artifact.id,
        notes.trim() || undefined,
      );
      setPromptPreview(preview);
      setShowPreview(true);
    } catch (err) {
      console.error('[ReviewPanel] Prompt preview failed:', err);
    } finally {
      setLoadingPreview(false);
    }
  };

  // Viewers always see just the comment input
  if (isViewer) {
    return (
      <div className="space-y-2">
        <h4 className="text-sm font-semibold text-gray-300">Comments</h4>
        <CommentsPanel projectId={projectId} artifactId={artifact.id} compact />
      </div>
    );
  }

  // Admin/Member + awaiting_review: feedback controls + comments inline
  if (isAwaitingReview) {
    return (
      <div className="space-y-3">
        {/* Feedback input */}
        <div className="space-y-3">
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-gray-400">Review Notes (optional)</label>
              {feedbackCount > 0 && (
                <span className="text-xs text-orange-400">
                  {feedbackCount} previous feedback{feedbackCount !== 1 ? 's' : ''}
                </span>
              )}
            </div>
            <textarea
              value={notes}
              onChange={(e) => { setNotes(e.target.value); setFeedbackSaved(false); }}
              className="w-full h-14 md:h-28 px-2 py-1 bg-gray-800 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
              placeholder="Add feedback for re-generation..."
            />
          </div>

          {showEditor && (
            <textarea
              value={editedContent || artifact.content || ''}
              onChange={(e) => setEditedContent(e.target.value)}
              className="w-full h-48 px-2 py-1 bg-gray-800 text-white text-sm rounded border border-gray-600 font-mono focus:border-blue-500 focus:outline-none"
            />
          )}
        </div>

        {/* Action buttons */}
        <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-gray-700">
          <button
            onClick={() => handleAction('approved')}
            disabled={submitting}
            className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            Approve
          </button>
          <button
            onClick={() => handleAction('save_feedback')}
            disabled={submitting || !notes.trim()}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            {feedbackSaved ? 'Feedback Saved' : 'Save Feedback'}
          </button>
          <button
            onClick={() => handleAction('rejected')}
            disabled={submitting}
            className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            Reject & Re-generate
          </button>
          <button
            onClick={() => setShowEditor(!showEditor)}
            className="px-3 py-1.5 bg-gray-600 hover:bg-gray-500 text-white text-xs rounded min-h-[44px] md:min-h-0"
          >
            {showEditor ? 'Hide Editor' : 'Edit & Approve'}
          </button>
          <button
            onClick={handlePreviewPrompt}
            disabled={loadingPreview}
            className="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 text-white text-xs rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            {loadingPreview ? 'Loading...' : showPreview ? 'Hide Prompt' : 'Preview Prompt'}
          </button>
        </div>

        {/* Prompt preview */}
        {showPreview && promptPreview && (
          <PromptPreviewPanel preview={promptPreview} />
        )}

        {/* Comments timeline (always visible) */}
        <div className="border-t border-gray-700 pt-2">
          <CommentsPanel projectId={projectId} artifactId={artifact.id} compact />
        </div>
      </div>
    );
  }

  // Admin/Member + NOT awaiting_review: compact comment input only
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-semibold text-gray-300">Comments</h4>
      <CommentsPanel projectId={projectId} artifactId={artifact.id} compact />
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
    <div className="space-y-2 border border-gray-700 rounded p-3 bg-gray-900/50 max-h-96 overflow-auto">
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
