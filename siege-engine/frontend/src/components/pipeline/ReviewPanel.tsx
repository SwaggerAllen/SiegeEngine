import { useState, useEffect } from 'react';
import { usePipelineStore } from '../../store/pipelineStore';
import { useAuthStore } from '../../store/authStore';
import { useDAGStore } from '../../store/dagStore';
import { listComments } from '../../api/comments';
import { reparseFanout } from '../../api/pipeline';
import type { Artifact } from '../../types/project';
import type { StageExecution } from '../../types/pipeline';
import { RESTARTABLE_STATUSES } from '../../types/pipeline';

interface ReviewPanelProps {
  projectId: string;
  artifact: Artifact;
  execution: StageExecution | undefined;
}

const REGENERATING_STATUSES = new Set(['running', 'ai_review', 'pending']);

export function ReviewPanel({ projectId, artifact, execution }: ReviewPanelProps) {
  const { resumeStage, resolveStale, acceptAndCascade, forceRestartStage, pruneArtifact } = usePipelineStore();
  const { user } = useAuthStore();
  const isViewer = user?.role === 'viewer';
  const [notes, setNotes] = useState('');
  const [editedContent, setEditedContent] = useState('');
  const [showEditor, setShowEditor] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedbackSaved, setFeedbackSaved] = useState(false);
  const [feedbackCount, setFeedbackCount] = useState(0);
  const [restarting, setRestarting] = useState(false);
  const [pruning, setPruning] = useState(false);
  const [reparsing, setReparsing] = useState(false);
  const [reparseResult, setReparseResult] = useState<string | null>(null);
  const fetchDAG = useDAGStore((s) => s.fetchDAG);
  const fetchDocumentsDAG = useDAGStore((s) => s.fetchDocumentsDAG);

  const isAwaitingReview = execution?.status === 'awaiting_review';
  const isRestartable = execution && RESTARTABLE_STATUSES.has(execution.status);
  const isStale = artifact.status === 'stale';
  const isBeingRegenerated = isStale && execution && REGENERATING_STATUSES.has(execution.status);
  const isInputDoc = artifact.artifact_type === 'project_doc';
  const isGenerating = artifact.status === 'generating' || artifact.status === 'ai_reviewing';
  const canPrune = !isViewer && !isInputDoc && !isGenerating;
  const isFanout = artifact.artifact_type === 'component_map' || artifact.artifact_type === 'sub_component_map';
  const canReparse = !isViewer && isFanout && !isGenerating;

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

  const handleStaleAction = async (action: string) => {
    setSubmitting(true);
    try {
      await resolveStale(
        projectId,
        artifact.id,
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

  const handleRestart = async () => {
    if (!execution) return;
    setRestarting(true);
    try {
      await forceRestartStage(projectId, execution.id);
    } catch (err) {
      console.error('Force restart failed:', err);
    } finally {
      setRestarting(false);
    }
  };

  const handlePrune = async () => {
    if (!window.confirm('Are you sure you want to prune this artifact? This will permanently delete it and its associated records.')) {
      return;
    }
    setPruning(true);
    try {
      await pruneArtifact(projectId, artifact.id);
    } catch (err) {
      console.error('Prune failed:', err);
    } finally {
      setPruning(false);
    }
  };

  const handleReparse = async () => {
    setReparsing(true);
    setReparseResult(null);
    try {
      const result = await reparseFanout(projectId, artifact.id);
      const msg = result.added.length > 0
        ? `Restored ${result.added.length}: ${result.added.join(', ')}`
        : 'No missing entities found';
      setReparseResult(msg);
      if (result.added.length > 0 || result.removed.length > 0) {
        await Promise.all([fetchDAG(projectId), fetchDocumentsDAG(projectId)]);
      }
    } catch (err) {
      console.error('Reparse failed:', err);
      setReparseResult('Reparse failed');
    } finally {
      setReparsing(false);
    }
  };

  const handleAcceptAndCascade = async () => {
    if (!window.confirm('Approve this artifact and regenerate all downstream dependents?')) return;
    setSubmitting(true);
    try {
      await acceptAndCascade(
        projectId,
        artifact.id,
        notes || undefined,
        showEditor && editedContent ? editedContent : undefined
      );
      setNotes('');
      setEditedContent('');
      setShowEditor(false);
      setFeedbackSaved(false);
    } finally {
      setSubmitting(false);
    }
  };

  // Auto-dismiss reparse result
  useEffect(() => {
    if (!reparseResult) return;
    const timer = setTimeout(() => setReparseResult(null), 5000);
    return () => clearTimeout(timer);
  }, [reparseResult]);

  // Show restart button for stuck/failed/rejected stages
  if (!isViewer && isRestartable && !isAwaitingReview) {
    const statusLabel = execution!.status === 'failed' ? 'Failed' :
                        execution!.status === 'rejected' ? 'Rejected' :
                        execution!.status === 'ai_review' ? 'Stuck in AI Review' : 'Stuck (Running)';
    const isRejected = execution!.status === 'rejected';
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-sm">
          <span className={`px-2 py-1 rounded text-white ${
            execution!.status === 'failed' || isRejected ? 'bg-red-700' : 'bg-blue-600 animate-pulse'
          }`}>
            {statusLabel}
          </span>
          {execution!.error_message && (
            <span className="text-red-400 text-xs truncate">{execution!.error_message}</span>
          )}
        </div>

        {isRejected && showEditor && (
          <textarea
            value={editedContent || artifact.content || ''}
            onChange={(e) => setEditedContent(e.target.value)}
            className="w-full h-48 px-2 py-1 bg-gray-800 text-white text-sm rounded border border-gray-600 font-mono focus:border-blue-500 focus:outline-none"
          />
        )}

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={handleRestart}
            disabled={restarting}
            className="px-4 py-2 bg-orange-600 hover:bg-orange-500 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            {restarting ? 'Restarting...' : '⟳ Force Restart Stage'}
          </button>
          {isRejected && (
            <>
              <button
                onClick={() => setShowEditor(!showEditor)}
                className="px-3 py-1.5 bg-gray-600 hover:bg-gray-500 text-white text-xs rounded min-h-[44px] md:min-h-0"
              >
                {showEditor ? 'Hide Editor' : 'Edit & Approve'}
              </button>
              {showEditor && (
                <button
                  onClick={() => handleAction('approved')}
                  disabled={submitting}
                  className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
                >
                  Approve
                </button>
              )}
            </>
          )}
        </div>
      </div>
    );
  }

  // Stale artifacts that are NOT being regenerated: show approve/reject UI
  if (!isViewer && isStale && !isBeingRegenerated) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-sm">
          <span className="px-2 py-1 rounded bg-orange-900 text-orange-300">
            Stale
          </span>
          <span className="text-xs text-gray-400">
            Upstream inputs have changed since this was generated.
          </span>
        </div>

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
            onClick={() => handleStaleAction('approved')}
            disabled={submitting}
            className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            Approve
          </button>
          <button
            onClick={handleAcceptAndCascade}
            disabled={submitting}
            className="px-3 py-1.5 bg-teal-600 hover:bg-teal-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            {submitting ? 'Cascading...' : 'Accept & Cascade'}
          </button>
          <button
            onClick={() => handleStaleAction('save_feedback')}
            disabled={submitting || !notes.trim()}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            {feedbackSaved ? 'Feedback Saved' : 'Save Feedback'}
          </button>
          <button
            onClick={() => handleStaleAction('rejected')}
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
          {canPrune && (
            <button
              onClick={handlePrune}
              disabled={pruning}
              className="px-3 py-1.5 bg-gray-700 hover:bg-red-700 text-gray-300 hover:text-white text-xs rounded disabled:opacity-50 transition-colors min-h-[44px] md:min-h-0"
            >
              {pruning ? 'Pruning...' : '🗑 Prune'}
            </button>
          )}
          {canReparse && (
            <button
              onClick={handleReparse}
              disabled={reparsing}
              className="px-3 py-1.5 bg-indigo-700 hover:bg-indigo-600 text-white text-xs rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
            >
              {reparsing ? 'Reparsing...' : 'Reparse Children'}
            </button>
          )}
          {reparseResult && (
            <span className={`text-xs ${reparseResult.startsWith('Restored') ? 'text-green-400' : reparseResult === 'No missing entities found' ? 'text-gray-400' : 'text-red-400'}`}>
              {reparseResult}
            </span>
          )}
        </div>
      </div>
    );
  }

  // Viewers or non-actionable: show prune/reparse buttons
  if (isViewer || !isAwaitingReview) {
    if (!canPrune && !canReparse) return null;
    return (
      <div className="pt-2 border-t border-gray-700 flex flex-wrap items-center gap-2">
        {canPrune && (
          <button
            onClick={handlePrune}
            disabled={pruning}
            className="px-3 py-1.5 bg-gray-700 hover:bg-red-700 text-gray-300 hover:text-white text-xs rounded disabled:opacity-50 transition-colors min-h-[44px] md:min-h-0"
          >
            {pruning ? 'Pruning...' : '🗑 Prune Node'}
          </button>
        )}
        {canReparse && (
          <button
            onClick={handleReparse}
            disabled={reparsing}
            className="px-3 py-1.5 bg-indigo-700 hover:bg-indigo-600 text-white text-xs rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            {reparsing ? 'Reparsing...' : 'Reparse Children'}
          </button>
        )}
        {reparseResult && (
          <span className={`text-xs ${reparseResult.startsWith('Restored') ? 'text-green-400' : reparseResult === 'No missing entities found' ? 'text-gray-400' : 'text-red-400'}`}>
            {reparseResult}
          </span>
        )}
      </div>
    );
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
          onClick={handleAcceptAndCascade}
          disabled={submitting}
          className="px-3 py-1.5 bg-teal-600 hover:bg-teal-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
        >
          {submitting ? 'Cascading...' : 'Accept & Cascade'}
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
        {canPrune && (
          <button
            onClick={handlePrune}
            disabled={pruning}
            className="px-3 py-1.5 bg-gray-700 hover:bg-red-700 text-gray-300 hover:text-white text-xs rounded disabled:opacity-50 transition-colors min-h-[44px] md:min-h-0"
          >
            {pruning ? 'Pruning...' : '🗑 Prune'}
          </button>
        )}
        {canReparse && (
          <button
            onClick={handleReparse}
            disabled={reparsing}
            className="px-3 py-1.5 bg-indigo-700 hover:bg-indigo-600 text-white text-xs rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            {reparsing ? 'Reparsing...' : 'Reparse Children'}
          </button>
        )}
        {reparseResult && (
          <span className={`text-xs ${reparseResult.startsWith('Restored') ? 'text-green-400' : reparseResult === 'No missing entities found' ? 'text-gray-400' : 'text-red-400'}`}>
            {reparseResult}
          </span>
        )}
      </div>
    </div>
  );
}
