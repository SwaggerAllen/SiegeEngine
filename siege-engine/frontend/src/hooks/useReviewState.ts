import { useState, useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '../store/authStore';
import { dagKeys } from './queries/useDAGQueries';
import { usePipelineConfigData, pipelineKeys } from './queries/usePipelineQueries';
import {
  useResumeStage,
  useResolveStale,
  useForceRestartStage,
  usePruneArtifact,
  useCancelStage,
} from './mutations/usePipelineMutations';
import { listComments, saveFeedback } from '../api/comments';
import { reparseFanout } from '../api/pipeline';
import { useLocalDraft } from './useLocalDraft';
import type { Artifact } from '../types/project';
import type { StageExecution } from '../types/pipeline';
import { RESTARTABLE_STATUSES } from '../types/pipeline';

const REGENERATING_STATUSES = new Set(['running', 'ai_review', 'pending']);

export interface ReviewStateResult {
  // Draft state
  notes: string;
  setNotes: (v: string | ((prev: string) => string)) => void;
  // Loading flags
  submitting: boolean;
  restarting: boolean;
  pruning: boolean;
  reparsing: boolean;
  cancelling: boolean;
  // Feedback
  feedbackSaved: boolean;
  feedbackCount: number;
  reparseResult: string | null;
  // Derived flags
  isViewer: boolean;
  isAwaitingReview: boolean;
  isRestartable: boolean;
  isStale: boolean;
  isBeingRegenerated: boolean;
  isInputDoc: boolean;
  isGenerating: boolean;
  canPrune: boolean;
  canReparse: boolean;
  artifactStageKey: string | null;
  // Handlers
  handleAction: (action: string) => Promise<void>;
  handleStaleAction: (action: string) => Promise<void>;
  handleRestart: () => Promise<void>;
  handlePrune: () => Promise<void>;
  handleReparse: () => Promise<void>;
  handleCancel: () => Promise<void>;
}

export function useReviewState(
  projectId: string,
  artifact: Artifact,
  execution: StageExecution | undefined,
): ReviewStateResult {
  const queryClient = useQueryClient();
  const resumeStageMutation = useResumeStage(projectId);
  const resolveStaleM = useResolveStale(projectId);
  const forceRestartMutation = useForceRestartStage(projectId);
  const pruneArtifactMutation = usePruneArtifact(projectId);
  const cancelStageMutation = useCancelStage(projectId);
  const config = usePipelineConfigData(projectId);
  const user = useAuthStore((s) => s.user);
  const isViewer = user?.role === 'viewer';

  const artifactStageKey =
    config?.stages.find((s) => s.output_artifact_type === artifact.artifact_type)?.stage_key ?? null;

  const [notes, setNotes, clearNotes] = useLocalDraft(`review-notes:${artifact.id}`);
  const [submitting, setSubmitting] = useState(false);
  const [feedbackSaved, setFeedbackSaved] = useState(false);
  const [feedbackCount, setFeedbackCount] = useState(0);
  const [restarting, setRestarting] = useState(false);
  const [pruning, setPruning] = useState(false);
  const [reparsing, setReparsing] = useState(false);
  const [reparseResult, setReparseResult] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const fetchedMissingExecRef = useRef<string | null>(null);
  // Use the execution id (primitive) rather than the execution object to avoid
  // re-firing when a new object with identical data is returned by TQ.
  const executionId = execution?.id ?? null;

  useEffect(() => {
    setFeedbackSaved(false);
    listComments(projectId, artifact.id)
      .then((comments) => {
        setFeedbackCount(comments.filter((c) => c.comment_type === 'feedback').length);
      })
      .catch(() => {});
    // Refresh executions if the artifact is awaiting_review but no execution
    // was matched. Guard with a ref so we only do this once per artifact to
    // avoid invalidate → re-render → still-no-execution → invalidate loops.
    if (
      artifact.status === 'awaiting_review' &&
      !executionId &&
      fetchedMissingExecRef.current !== artifact.id
    ) {
      fetchedMissingExecRef.current = artifact.id;
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
    }
  // executionId is a stable primitive — avoids firing on every TQ re-render
  // that returns a new execution object with the same id.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, artifact.id, artifact.status, executionId]);

  useEffect(() => {
    if (!reparseResult) return;
    const timer = setTimeout(() => setReparseResult(null), 5000);
    return () => clearTimeout(timer);
  }, [reparseResult]);

  // Derived flags
  const isAwaitingReview =
    execution?.status === 'awaiting_review' || artifact.status === 'awaiting_review';
  const isRestartable = execution != null && RESTARTABLE_STATUSES.has(execution.status);
  const isStale = !!(artifact as Record<string, unknown>).is_stale;
  const isBeingRegenerated =
    isStale && execution != null && REGENERATING_STATUSES.has(execution.status);
  const isInputDoc = artifact.artifact_type === 'project_doc';
  const isGenerating = artifact.status === 'generating' || artifact.status === 'ai_reviewing';
  const isFanout =
    artifact.artifact_type === 'component_map' || artifact.artifact_type === 'sub_component_map';
  const canPrune = !isViewer && !isInputDoc && !isGenerating;
  const canReparse = !isViewer && isFanout && !isGenerating;

  // Save feedback uses a dedicated endpoint that works regardless of
  // artifact status or execution state — no pipeline job queue involved.
  const handleSaveFeedback = async () => {
    if (!notes.trim()) return;
    setSubmitting(true);
    try {
      await saveFeedback(projectId, artifact.id, notes);
      setFeedbackSaved(true);
      setFeedbackCount((c) => c + 1);
      clearNotes();
    } catch (err) {
      console.error('Save feedback failed:', err);
    } finally {
      setSubmitting(false);
    }
  };

  // Define handleStaleAction first — handleAction delegates to it for input docs.
  const handleStaleAction = async (action: string) => {
    if (action === 'save_feedback') return handleSaveFeedback();
    setSubmitting(true);
    try {
      await resolveStaleM.mutateAsync({
        artifactId: artifact.id,
        action,
        notes: notes || undefined,
      });
      clearNotes();
      setFeedbackSaved(false);
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
    } catch (err) {
      console.error('Stale action failed:', err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleAction = async (action: string) => {
    if (action === 'save_feedback') return handleSaveFeedback();
    if (!execution) {
      if (isInputDoc) await handleStaleAction(action);
      return;
    }
    setSubmitting(true);
    try {
      await resumeStageMutation.mutateAsync({
        executionId: execution.id,
        action,
        notes: notes || undefined,
      });
      clearNotes();
      setFeedbackSaved(false);
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
    } catch (err) {
      console.error('Resume stage failed:', err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRestart = async () => {
    if (!execution) return;
    setRestarting(true);
    try {
      await forceRestartMutation.mutateAsync(execution.id);
    } catch (err) {
      console.error('Force restart failed:', err);
    } finally {
      setRestarting(false);
    }
  };

  const handlePrune = async () => {
    if (
      !window.confirm(
        'Are you sure you want to prune this artifact? This will permanently delete it and its associated records.',
      )
    )
      return;
    setPruning(true);
    try {
      await pruneArtifactMutation.mutateAsync(artifact.id);
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
      const parts: string[] = [];
      if (result.added.length > 0) parts.push(`Added ${result.added.length}: ${result.added.join(', ')}`);
      if (result.removed.length > 0) parts.push(`Removed ${result.removed.length}: ${result.removed.join(', ')}`);
      if (result.updated.length > 0) parts.push(`Updated ${result.updated.length}: ${result.updated.join(', ')}`);
      const msg = parts.length > 0 ? parts.join('. ') : 'No changes detected';
      setReparseResult(msg);
      // Always invalidate — even dependency-only updates affect the DAG edges
      queryClient.invalidateQueries({ queryKey: dagKeys.workflow(projectId) });
      queryClient.invalidateQueries({ queryKey: dagKeys.documents(projectId) });
    } catch (err) {
      console.error('Reparse failed:', err);
      setReparseResult('Reparse failed');
    } finally {
      setReparsing(false);
    }
  };

  const handleCancel = async () => {
    if (!execution) return;
    setCancelling(true);
    try {
      await cancelStageMutation.mutateAsync(execution.id);
    } catch (err) {
      console.error('Cancel failed:', err);
    } finally {
      setCancelling(false);
    }
  };

  return {
    notes,
    setNotes,
    submitting,
    restarting,
    pruning,
    reparsing,
    cancelling,
    feedbackSaved,
    feedbackCount,
    reparseResult,
    isViewer,
    isAwaitingReview,
    isRestartable,
    isStale,
    isBeingRegenerated,
    isInputDoc,
    isGenerating,
    canPrune,
    canReparse,
    artifactStageKey,
    handleAction,
    handleStaleAction,
    handleRestart,
    handlePrune,
    handleReparse,
    handleCancel,
  };
}
