import { useState, useEffect } from 'react';
import { usePipelineStore } from '../../store/pipelineStore';
import { useAuthStore } from '../../store/authStore';
import { listComments } from '../../api/comments';
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

  const isAwaitingReview = execution?.status === 'awaiting_review';

  // Reset to blank when switching artifacts; fetch feedback count
  useEffect(() => {
    setNotes('');
    setFeedbackSaved(false);
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

  // Viewers or non-awaiting_review: nothing to show
  if (isViewer || !isAwaitingReview) {
    return null;
  }

  // Admin/Member + awaiting_review: feedback controls only
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
      </div>
    </div>
  );
}
