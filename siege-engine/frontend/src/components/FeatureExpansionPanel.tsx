import { useState } from 'react';
import Markdown from 'react-markdown';
import { useExpansion } from '../hooks/queries/useExpansionQueries';
import {
  useApproveMutation,
  useDiscardMutation,
  useFeedbackMutation,
} from '../hooks/mutations/useExpansionMutations';

interface Props {
  projectId: string;
}

export function FeatureExpansionPanel({ projectId }: Props) {
  const { data, error, isLoading } = useExpansion(projectId);
  const feedbackMutation = useFeedbackMutation(projectId);
  const approveMutation = useApproveMutation(projectId);
  const discardMutation = useDiscardMutation(projectId);

  const [feedback, setFeedback] = useState('');

  if (isLoading) {
    return (
      <div className="p-6 text-gray-400 text-sm">Loading feature expansion…</div>
    );
  }
  if (error) {
    return (
      <div className="p-6 text-red-400 text-sm">
        Failed to load feature expansion:{' '}
        {error instanceof Error ? error.message : 'Unknown error'}
      </div>
    );
  }
  if (!data) return null;

  const { node, pending_draft, generation_status, last_error } = data;
  const isBusy =
    feedbackMutation.isPending ||
    approveMutation.isPending ||
    discardMutation.isPending;

  const submitFeedback = () => {
    const trimmed = feedback.trim();
    if (!trimmed) return;
    feedbackMutation.mutate(trimmed, {
      onSuccess: () => {
        setFeedback('');
      },
    });
  };

  const retry = () => {
    feedbackMutation.mutate('');
  };

  // State 1: generating, no pending draft yet.
  if (generation_status === 'running' && !pending_draft) {
    return (
      <div className="p-6 flex flex-col items-center justify-center gap-3 text-gray-300">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-600 border-t-blue-400" />
        <div className="text-sm">Generating feature expansion…</div>
      </div>
    );
  }

  // State 2: pending draft present (review mode).
  if (pending_draft) {
    return (
      <div className="p-6 space-y-4 max-w-4xl mx-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Feature Expansion — Draft</h2>
          {generation_status === 'running' && (
            <span className="text-xs text-gray-400">regenerating…</span>
          )}
        </div>
        <div className="prose prose-invert max-w-none border border-gray-700 rounded p-4 bg-gray-800/50">
          <Markdown>{pending_draft.content}</Markdown>
        </div>
        <div className="space-y-2">
          <label className="block text-xs text-gray-400">
            Feedback for regeneration (optional)
          </label>
          <textarea
            className="w-full h-24 bg-gray-900 border border-gray-700 rounded p-2 text-sm"
            placeholder="e.g. Add reporting, tighten scope on auth…"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            disabled={isBusy}
          />
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            type="button"
            onClick={submitFeedback}
            disabled={isBusy || !feedback.trim()}
            className="px-4 py-2 text-sm rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-40"
          >
            Regenerate
          </button>
          <button
            type="button"
            onClick={() => approveMutation.mutate(pending_draft.id)}
            disabled={isBusy}
            className="px-4 py-2 text-sm rounded bg-green-700 hover:bg-green-600 disabled:opacity-40"
          >
            Approve
          </button>
          <button
            type="button"
            onClick={() => discardMutation.mutate(pending_draft.id)}
            disabled={isBusy}
            className="px-4 py-2 text-sm rounded bg-red-900 hover:bg-red-800 disabled:opacity-40"
          >
            Discard
          </button>
        </div>
      </div>
    );
  }

  // State 4: failed, no content, no pending draft.
  if (generation_status === 'failed' && !node.content) {
    return (
      <div className="p-6 max-w-4xl mx-auto space-y-4">
        <div className="p-4 border border-red-800 bg-red-950/40 rounded text-sm text-red-300">
          <div className="font-semibold mb-1">Generation failed</div>
          {last_error && <div className="text-red-400/80">{last_error}</div>}
        </div>
        <button
          type="button"
          onClick={retry}
          disabled={isBusy}
          className="px-4 py-2 text-sm rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40"
        >
          Retry
        </button>
      </div>
    );
  }

  // State 3: approved content, no pending draft. The expansion node
  // is read-only after approval per v2 spec — further feature-layer
  // edits land on individual feature nodes (Phase 2), not by
  // re-editing the expansion prose. So no "Request revision" button.
  if (node.content) {
    return (
      <div className="p-6 space-y-4 max-w-4xl mx-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">{node.name}</h2>
          <span className="text-xs text-gray-500 uppercase tracking-wide">
            Approved · read-only
          </span>
        </div>
        <div className="prose prose-invert max-w-none border border-gray-700 rounded p-4 bg-gray-800/50">
          <Markdown>{node.content}</Markdown>
        </div>
        <div className="text-xs text-gray-500 italic">
          Further feature-layer edits happen on individual feature
          nodes once Phase 2 lands.
        </div>
      </div>
    );
  }

  // State 3b: node exists but has no content and no pending draft —
  // pre-bootstrap empty state (shouldn't normally be reached in the
  // happy path, but we render something sensible instead of nothing).
  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{node.name}</h2>
      </div>
      <div className="text-sm text-gray-400 italic">
        No approved content yet.
      </div>
    </div>
  );
}
