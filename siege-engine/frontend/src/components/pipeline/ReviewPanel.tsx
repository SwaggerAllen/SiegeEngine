import { useState } from 'react';
import { useIsRunning, usePipelineRuns } from '../../hooks/queries/usePipelineQueries';
import { useStartPipeline, useResumeRun, useRegenDownstream } from '../../hooks/mutations/usePipelineMutations';
import { useReviewState } from '../../hooks/useReviewState';
import { FeedbackSection } from './FeedbackSection';
import { ActionButtonsBar } from './ActionButtonsBar';
import type { Artifact } from '../../types/project';
import type { StageExecution, PipelineStartOptions } from '../../types/pipeline';

const STOP_POINT_OPTIONS = [
  { value: 'end_of_phase', label: 'End of phase' },
  { value: 'before_code', label: 'Before code generation' },
  { value: 'every_artifact', label: 'After every artifact' },
];

const STOP_POINT_REGEN = { value: 'regen_downstream', label: 'Regen downstream only' };

// ---------------------------------------------------------------------------
// RunFromNodeControls — inline run launcher shown inside the node panel
// ---------------------------------------------------------------------------

function RunFromNodeControls({
  projectId,
  stageKey,
  componentKey,
  artifactId,
}: {
  projectId: string;
  stageKey: string | null;
  componentKey: string | null;
  artifactId?: string;
}) {
  const startPipelineMutation = useStartPipeline(projectId);
  const resumeRunMutation = useResumeRun(projectId);
  const regenDownstreamMutation = useRegenDownstream(projectId);
  const isRunning = useIsRunning(projectId);
  const { data: runs = [] } = usePipelineRuns(projectId);
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<'start' | 'resume'>('start');
  const [aiLoops, setAiLoops] = useState(1);
  const [stopPoint, setStopPoint] = useState('end_of_phase');
  const [starting, setStarting] = useState(false);

  const hasCompletedRun = runs.some(
    (r) =>
      r.status === 'completed' ||
      r.status === 'paused' ||
      r.status === 'cancelled' ||
      r.status === 'failed',
  );
  const isRegen = stopPoint === 'regen_downstream';

  if (isRunning) return null;

  const handleStart = async () => {
    setStarting(true);
    try {
      if (isRegen && artifactId) {
        await regenDownstreamMutation.mutateAsync(artifactId);
      } else {
        const options: PipelineStartOptions = {
          ai_loops: aiLoops,
          stop_point: stopPoint,
          start_stage_key: stageKey,
          start_component_key: mode === 'resume' ? null : componentKey,
        };
        if (mode === 'resume') {
          await resumeRunMutation.mutateAsync(options);
        } else {
          await startPipelineMutation.mutateAsync(options);
        }
      }
    } catch (err) {
      console.error('Run start failed:', err);
    } finally {
      setStarting(false);
      setExpanded(false);
    }
  };

  return (
    <div className="border-t border-gray-700 pt-2 mt-2">
      {!expanded ? (
        <button
          onClick={() => setExpanded(true)}
          className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-xs rounded min-h-[44px] md:min-h-0 flex items-center gap-1"
        >
          <span>Start Run</span>
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      ) : (
        <div className="space-y-3 bg-gray-800/50 rounded-lg p-3">
          <h4 className="text-xs font-semibold text-gray-300">Run Configuration</h4>

          <div>
            <label className="block text-xs text-gray-400 mb-1">Run type</label>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as 'start' | 'resume')}
              className="w-full px-2 py-1.5 bg-gray-700 text-white text-xs rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
            >
              <option value="start">Fresh Start from here</option>
              {hasCompletedRun && <option value="resume">Resume from here</option>}
            </select>
          </div>

          {!isRegen && (
            <div>
              <label className="block text-xs text-gray-400 mb-1">AI self-improvement loops</label>
              <input
                type="number"
                min={0}
                max={10}
                value={aiLoops}
                onChange={(e) =>
                  setAiLoops(Math.max(0, Math.min(10, parseInt(e.target.value) || 0)))
                }
                className="w-16 px-2 py-1 bg-gray-700 text-white text-xs rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
              />
            </div>
          )}

          <div>
            <label className="block text-xs text-gray-400 mb-1">Stop at</label>
            <select
              value={stopPoint}
              onChange={(e) => setStopPoint(e.target.value)}
              className="w-full px-2 py-1.5 bg-gray-700 text-white text-xs rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
            >
              {STOP_POINT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
              {artifactId && (
                <option value={STOP_POINT_REGEN.value}>{STOP_POINT_REGEN.label}</option>
              )}
            </select>
            {isRegen && (
              <p className="text-xs text-gray-500 mt-1">
                Only regenerates already-generated nodes downstream of this artifact.
              </p>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleStart}
              disabled={starting}
              className={`px-3 py-1.5 text-white text-xs rounded disabled:opacity-50 min-h-[44px] md:min-h-0 ${
                isRegen
                  ? 'bg-teal-600 hover:bg-teal-700'
                  : mode === 'resume'
                    ? 'bg-blue-600 hover:bg-blue-700'
                    : 'bg-green-600 hover:bg-green-700'
              }`}
            >
              {starting
                ? 'Starting...'
                : isRegen
                  ? 'Regen Downstream'
                  : mode === 'resume'
                    ? 'Resume'
                    : 'Start'}
            </button>
            <button
              onClick={() => setExpanded(false)}
              className="px-3 py-1.5 bg-gray-600 hover:bg-gray-500 text-white text-xs rounded min-h-[44px] md:min-h-0"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ReviewPanel
// ---------------------------------------------------------------------------

interface ReviewPanelProps {
  projectId: string;
  artifact: Artifact;
  execution: StageExecution | undefined;
  /**
   * 'actions' (default) — show status badges and action buttons (approve/reject/restart/cancel).
   *   Rendered in the bottom pane when the DAG is visible.
   * 'feedback' — show the feedback textarea and save/submit buttons only.
   *   Rendered in the bottom pane when the artifact editor is visible (review mode).
   */
  mode?: 'actions' | 'feedback';
  /** @deprecated kept for call-site compatibility; has no effect */
  compactMobile?: boolean;
}

export function ReviewPanel({ projectId, artifact, execution, mode = 'actions' }: ReviewPanelProps) {
  const s = useReviewState(projectId, artifact, execution);

  const runControls = !s.isInputDoc ? (
    <RunFromNodeControls
      projectId={projectId}
      stageKey={s.artifactStageKey}
      componentKey={artifact.component_key}
      artifactId={artifact.id}
    />
  ) : null;

  // ── Restartable (failed / rejected / stuck) ──────────────────────────────
  if (!s.isViewer && s.isRestartable && !s.isAwaitingReview && !s.isGenerating) {
    // Feedback mode: nothing actionable here (no feedback textarea for error recovery)
    if (mode === 'feedback') return null;

    const statusLabel =
      execution!.status === 'failed'
        ? 'Failed'
        : execution!.status === 'rejected'
          ? 'Rejected'
          : execution!.status === 'ai_review'
            ? 'Stuck in AI Review'
            : 'Stuck (Running)';
    const isRejected = execution!.status === 'rejected';

    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-sm">
          <span
            className={`px-2 py-1 rounded text-white ${
              execution!.status === 'failed' || isRejected
                ? 'bg-red-700'
                : 'bg-blue-600 animate-pulse'
            }`}
          >
            {statusLabel}
          </span>
          {execution!.error_message && (
            <span className="text-red-400 text-xs truncate">{execution!.error_message}</span>
          )}
        </div>

        {isRejected && s.showEditor && (
          <textarea
            value={s.editedContent || artifact.content || ''}
            onChange={(e) => s.setEditedContent(e.target.value)}
            className="w-full h-48 px-2 py-1 bg-gray-800 text-white text-sm rounded border border-gray-600 font-mono focus:border-blue-500 focus:outline-none"
          />
        )}

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={s.handleRestart}
            disabled={s.restarting}
            className="px-4 py-2 bg-orange-600 hover:bg-orange-500 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            {s.restarting ? 'Restarting...' : '⟳ Force Restart Stage'}
          </button>
          {isRejected && (
            <>
              <button
                onClick={() => s.setShowEditor(!s.showEditor)}
                className="px-3 py-1.5 bg-gray-600 hover:bg-gray-500 text-white text-xs rounded min-h-[44px] md:min-h-0"
              >
                {s.showEditor ? 'Hide Editor' : 'Edit & Approve'}
              </button>
              {s.showEditor && (
                <button
                  onClick={() => s.handleAction('approved')}
                  disabled={s.submitting}
                  className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
                >
                  Approve
                </button>
              )}
            </>
          )}
        </div>
        {runControls}
      </div>
    );
  }

  // ── Stale, not being regenerated ─────────────────────────────────────────
  if (!s.isViewer && s.isStale && !s.isBeingRegenerated) {
    if (mode === 'feedback') {
      return (
        <div className="space-y-3">
          <FeedbackSection
            notes={s.notes}
            onNotesChange={(v) => { s.setNotes(v); }}
            feedbackCount={s.feedbackCount}
            placeholder="Add feedback for re-generation..."
          />
          <div className="flex items-center gap-2 pt-1 border-t border-gray-700">
            <button
              onClick={() => s.handleStaleAction('save_feedback')}
              disabled={s.submitting || !s.notes.trim()}
              className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
            >
              {s.feedbackSaved ? 'Feedback Saved' : 'Save Feedback'}
            </button>
          </div>
        </div>
      );
    }

    // actions mode
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-sm">
          <span className="px-2 py-1 rounded bg-orange-900 text-orange-300">Stale</span>
          <span className="text-xs text-gray-400">
            Upstream inputs have changed since this was generated.
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button
            onClick={() => s.handleStaleAction('approved')}
            disabled={s.submitting}
            className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            Approve
          </button>
          <button
            onClick={() => s.handleStaleAction('rejected')}
            disabled={s.submitting}
            className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            Reject &amp; Re-generate
          </button>
          <button
            onClick={() => s.setShowEditor(!s.showEditor)}
            className="px-3 py-1.5 bg-gray-600 hover:bg-gray-500 text-white text-xs rounded min-h-[44px] md:min-h-0"
          >
            {s.showEditor ? 'Hide Editor' : 'Edit & Approve'}
          </button>
          <ActionButtonsBar
            canPrune={s.canPrune}
            canReparse={s.canReparse}
            pruning={s.pruning}
            reparsing={s.reparsing}
            reparseResult={s.reparseResult}
            onPrune={s.handlePrune}
            onReparse={s.handleReparse}
          />
        </div>
        {runControls}
      </div>
    );
  }

  // ── Actively generating ───────────────────────────────────────────────────
  if (
    !s.isViewer &&
    s.isGenerating &&
    execution &&
    (execution.status === 'running' || execution.status === 'ai_review' || execution.status === 'pending')
  ) {
    // Feedback mode: nothing to show while generating
    if (mode === 'feedback') return null;

    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-sm">
          <span className="px-2 py-1 rounded bg-blue-600 text-white animate-pulse">
            {execution.status === 'ai_review' ? 'AI Reviewing' : 'Generating'}
          </span>
          <span className="text-xs text-gray-400">This artifact is being generated...</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={s.handleCancel}
            disabled={s.cancelling}
            className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            {s.cancelling ? 'Cancelling...' : 'Cancel Generation'}
          </button>
        </div>
      </div>
    );
  }

  // ── Approved (non-viewer, non-input doc) ──────────────────────────────────
  const isApproved = artifact.status === 'approved' && execution?.status === 'approved';
  if (!s.isViewer && !s.isAwaitingReview && isApproved && !s.isInputDoc) {
    if (mode === 'feedback') {
      return (
        <div className="space-y-3">
          <FeedbackSection
            notes={s.notes}
            onNotesChange={(v) => { s.setNotes(v); }}
            feedbackCount={s.feedbackCount}
            label="Request Changes (optional)"
            placeholder="Add feedback to request changes..."
          />
          <div className="flex items-center gap-2 pt-1 border-t border-gray-700">
            <button
              onClick={() => s.handleAction('save_feedback')}
              disabled={s.submitting || !s.notes.trim()}
              className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
            >
              {s.feedbackSaved ? 'Feedback Saved' : 'Save Feedback'}
            </button>
          </div>
        </div>
      );
    }

    // actions mode
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button
            onClick={() => s.handleAction('rejected')}
            disabled={s.submitting || !s.notes.trim()}
            className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            {s.submitting ? 'Requesting...' : 'Request Changes & Re-generate'}
          </button>
          <ActionButtonsBar
            canPrune={s.canPrune}
            canReparse={s.canReparse}
            pruning={s.pruning}
            reparsing={s.reparsing}
            reparseResult={s.reparseResult}
            onPrune={s.handlePrune}
            onReparse={s.handleReparse}
          />
        </div>
        <RunFromNodeControls
          projectId={projectId}
          stageKey={s.artifactStageKey}
          componentKey={artifact.component_key}
          artifactId={artifact.id}
        />
      </div>
    );
  }

  // ── Viewer or non-actionable ──────────────────────────────────────────────
  if (s.isViewer || !s.isAwaitingReview) {
    // Feedback mode: nothing to show for viewer/non-actionable
    if (mode === 'feedback') return null;

    return (
      <div className="space-y-2">
        {(s.canPrune || s.canReparse) && (
          <div className="pt-2 border-t border-gray-700 flex flex-wrap items-center gap-2">
            <ActionButtonsBar
              canPrune={s.canPrune}
              canReparse={s.canReparse}
              pruning={s.pruning}
              reparsing={s.reparsing}
              reparseResult={s.reparseResult}
              onPrune={s.handlePrune}
              onReparse={s.handleReparse}
              pruneLabel={execution ? '🗑 Prune' : '🗑 Prune Node'}
            />
          </div>
        )}
        {!s.isViewer && runControls}
      </div>
    );
  }

  // ── Awaiting review (default) ─────────────────────────────────────────────
  if (mode === 'feedback') {
    return (
      <div className="space-y-3">
        <FeedbackSection
          notes={s.notes}
          onNotesChange={(v) => { s.setNotes(v); }}
          feedbackCount={s.feedbackCount}
          placeholder="Add feedback for re-generation..."
        />
        <div className="flex items-center gap-2 pt-1 border-t border-gray-700">
          <button
            onClick={() => s.handleAction('save_feedback')}
            disabled={s.submitting || !s.notes.trim()}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            {s.feedbackSaved ? 'Feedback Saved' : 'Save Feedback'}
          </button>
        </div>
      </div>
    );
  }

  // actions mode — awaiting review
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          onClick={() => s.handleAction('approved')}
          disabled={s.submitting}
          className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
        >
          Approve
        </button>
        <button
          onClick={() => s.handleAction('rejected')}
          disabled={s.submitting}
          className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
        >
          Reject &amp; Re-generate
        </button>
        <button
          onClick={() => s.setShowEditor(!s.showEditor)}
          className="px-3 py-1.5 bg-gray-600 hover:bg-gray-500 text-white text-xs rounded min-h-[44px] md:min-h-0"
        >
          {s.showEditor ? 'Hide Editor' : 'Edit & Approve'}
        </button>
        <ActionButtonsBar
          canPrune={s.canPrune}
          canReparse={s.canReparse}
          pruning={s.pruning}
          reparsing={s.reparsing}
          reparseResult={s.reparseResult}
          onPrune={s.handlePrune}
          onReparse={s.handleReparse}
        />
      </div>
      {runControls}
    </div>
  );
}
