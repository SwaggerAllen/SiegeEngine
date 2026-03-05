import { useState } from 'react';
import { usePipelineStore } from '../../store/pipelineStore';
import type { Artifact } from '../../types/project';
import type { StageExecution } from '../../types/pipeline';

type ReviewTab = 'ai' | 'feedback';

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
  const [activeTab, setActiveTab] = useState<ReviewTab>('ai');

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
      // Clear form for next review cycle
      setNotes('');
      setEditedContent('');
      setShowEditor(false);
    } finally {
      setSubmitting(false);
    }
  };

  const feedback = artifact.ai_review_feedback as any;
  const hasDocument = !!feedback?.document;

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-semibold text-yellow-400">Review Required</h4>

      {/* Tabs */}
      <div className="flex border-b border-gray-700">
        <button
          onClick={() => setActiveTab('ai')}
          className={`py-1.5 px-3 text-xs border-b-2 min-h-[44px] md:min-h-0 ${
            activeTab === 'ai'
              ? 'border-blue-500 text-white'
              : 'border-transparent text-gray-400 hover:text-white'
          }`}
        >
          AI Review
        </button>
        <button
          onClick={() => setActiveTab('feedback')}
          className={`py-1.5 px-3 text-xs border-b-2 min-h-[44px] md:min-h-0 ${
            activeTab === 'feedback'
              ? 'border-blue-500 text-white'
              : 'border-transparent text-gray-400 hover:text-white'
          }`}
        >
          Your Feedback
        </button>
      </div>

      {/* AI Review tab */}
      {activeTab === 'ai' && feedback && (
        <div className="bg-gray-800 p-3 rounded text-sm">
          <p className="text-gray-400 mb-1">AI Review:</p>
          <p className="text-white">
            Quality: {feedback.overall_quality}/10
          </p>
          <p className="text-white">
            Recommendation:{' '}
            <span
              className={
                feedback.recommendation === 'approve'
                  ? 'text-green-400'
                  : 'text-yellow-400'
              }
            >
              {feedback.recommendation}
            </span>
          </p>
          {hasDocument && (
            <p className="text-gray-400 text-xs mt-2">
              See the "AI Feedback" tab in the editor for the full review document.
            </p>
          )}
          {/* Backward compatibility: show old-format issues if present */}
          {!hasDocument && feedback.issues?.length > 0 && (
            <ul className="mt-1 space-y-1">
              {feedback.issues.map(
                (issue: any, i: number) => (
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
                )
              )}
            </ul>
          )}
        </div>
      )}

      {activeTab === 'ai' && !feedback && (
        <p className="text-gray-500 text-xs">No AI review feedback available.</p>
      )}

      {/* Your Feedback tab */}
      {activeTab === 'feedback' && (
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Review Notes (optional)</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full h-28 px-2 py-1 bg-gray-800 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
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
      )}

      {/* Persistent action buttons */}
      <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-gray-700">
        <button
          onClick={() => handleAction('approved')}
          disabled={submitting}
          className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
        >
          Approve
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
