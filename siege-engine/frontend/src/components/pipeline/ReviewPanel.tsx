import { useState, useEffect } from 'react';
import { usePipelineStore } from '../../store/pipelineStore';
import type { Artifact } from '../../types/project';
import type { StageExecution } from '../../types/pipeline';

interface ReviewPanelProps {
  projectId: string;
  artifact: Artifact;
  execution: StageExecution | undefined;
}

export function ReviewPanel({ projectId, artifact, execution }: ReviewPanelProps) {
  const { resumeStage } = usePipelineStore();
  const [notes, setNotes] = useState('');
  const [editedContent, setEditedContent] = useState('');
  const [showEditor, setShowEditor] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedbackSaved, setFeedbackSaved] = useState(false);

  // Pre-populate notes with existing human_review_notes
  useEffect(() => {
    if (artifact.human_review_notes) {
      setNotes(artifact.human_review_notes);
    } else {
      setNotes('');
    }
    setFeedbackSaved(false);
  }, [artifact.id, artifact.human_review_notes]);

  if (!execution || execution.status !== 'awaiting_review') return null;

  const handleAction = async (action: string) => {
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

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-semibold text-yellow-400">Your Feedback</h4>

      {artifact.human_review_notes && (
        <div className="text-xs text-blue-400 flex items-center gap-1">
          <span>Feedback saved on this artifact</span>
        </div>
      )}

      <div className="space-y-3">
        <div>
          <label className="block text-xs text-gray-400 mb-1">Review Notes (optional)</label>
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

        <button
          onClick={() => setShowEditor(!showEditor)}
          className="px-3 py-1.5 bg-gray-600 hover:bg-gray-500 text-white text-xs rounded min-h-[44px] md:min-h-0"
        >
          {showEditor ? 'Hide Editor' : 'Edit & Approve'}
        </button>
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
      </div>
    </div>
  );
}
