import { useState } from 'react';
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
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="border-t border-gray-700 pt-4 mt-4 space-y-3">
      <h4 className="text-sm font-semibold text-yellow-400">Review Required</h4>

      {artifact.ai_review_feedback && (
        <div className="bg-gray-800 p-3 rounded text-sm">
          <p className="text-gray-400 mb-1">AI Review:</p>
          <p className="text-white">
            Quality: {(artifact.ai_review_feedback as any).overall_quality}/10
          </p>
          <p className="text-white">
            Recommendation: {(artifact.ai_review_feedback as any).recommendation}
          </p>
          {(artifact.ai_review_feedback as any).issues?.length > 0 && (
            <ul className="mt-1 space-y-1">
              {(artifact.ai_review_feedback as any).issues.map(
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

      <div>
        <label className="block text-xs text-gray-400 mb-1">Review Notes (optional)</label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="w-full h-20 px-2 py-1 bg-gray-800 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
          placeholder="Add feedback for re-generation..."
        />
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={() => handleAction('approved')}
          disabled={submitting}
          className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded disabled:opacity-50"
        >
          Approve
        </button>
        <button
          onClick={() => handleAction('rejected')}
          disabled={submitting}
          className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm rounded disabled:opacity-50"
        >
          Reject & Re-generate
        </button>
        <button
          onClick={() => setShowEditor(!showEditor)}
          className="px-3 py-1.5 bg-gray-600 hover:bg-gray-500 text-white text-sm rounded"
        >
          {showEditor ? 'Hide Editor' : 'Edit & Approve'}
        </button>
      </div>

      {showEditor && (
        <textarea
          value={editedContent || artifact.content || ''}
          onChange={(e) => setEditedContent(e.target.value)}
          className="w-full h-64 px-2 py-1 bg-gray-800 text-white text-sm rounded border border-gray-600 font-mono focus:border-blue-500 focus:outline-none"
        />
      )}
    </div>
  );
}
