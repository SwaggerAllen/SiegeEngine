import { useState } from 'react';
import { useReferenceDetail } from '../hooks/queries/useReferenceQueries';
import {
  useApproveReferenceMutation,
  useDeleteReferenceMutation,
  useDiscardReferenceMutation,
  useRemoveReferenceEdgeMutation,
  useUpdateReferenceMutation,
} from '../hooks/mutations/useReferenceMutations';
import { XmlDocument } from './xml/XmlDocument';
import { referencesRenderers } from './xml/referencesRenderers';

interface Props {
  projectId: string;
  refId: string | null;
  onDeleted?: () => void;
}

/**
 * Detail + draft-review panel for a single reference.
 *
 * Reads the standard bootstrap-tier shape (node / pending_draft /
 * generation_status / latest_telemetry) from the ref API, plus
 * the ref-specific outgoing/incoming edge lists.
 *
 * Refs are NOT frozen after approval, so the feedback button is
 * always enabled — that's the one behavioural divergence from
 * the bootstrap tiers.
 */
export function ReferencePanel({ projectId, refId, onDeleted }: Props) {
  const { data, isLoading, error } = useReferenceDetail(projectId, refId);
  const [feedbackText, setFeedbackText] = useState('');

  // Hook order is fixed across renders; bind even when refId is
  // null (we early-return before using them).
  const updateMutation = useUpdateReferenceMutation(projectId, refId ?? '');
  const approveMutation = useApproveReferenceMutation(projectId, refId ?? '');
  const discardMutation = useDiscardReferenceMutation(projectId, refId ?? '');
  const deleteMutation = useDeleteReferenceMutation(projectId);
  const removeEdgeMutation = useRemoveReferenceEdgeMutation(projectId);

  if (!refId) {
    return (
      <div className="text-sm text-gray-500 italic p-4">
        Select a reference to view its content.
      </div>
    );
  }
  if (isLoading) {
    return <div className="p-4 text-gray-400 text-sm">Loading…</div>;
  }
  if (error || !data) {
    return (
      <div className="p-4 text-red-400 text-sm">
        Failed to load reference.
      </div>
    );
  }

  const { node, pending_draft, generation_status, last_error, latest_telemetry } = data;
  const isRunning = generation_status === 'running';
  const hasDraft = pending_draft !== null;
  const hasContent = !!node.content;

  const handleFeedback = () => {
    updateMutation.mutate(feedbackText.trim(), {
      onSuccess: () => setFeedbackText(''),
    });
  };

  const handleApprove = () => {
    if (!pending_draft) return;
    approveMutation.mutate(pending_draft.id);
  };

  const handleDiscard = () => {
    if (!pending_draft) return;
    discardMutation.mutate(pending_draft.id);
  };

  const handleDelete = () => {
    if (!window.confirm(`Delete reference "${node.name}"?`)) return;
    deleteMutation.mutate(refId, { onSuccess: () => onDeleted?.() });
  };

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-bold text-white m-0">{node.name}</h2>
          <div className="text-xs font-mono text-gray-500">{node.id}</div>
        </div>
        <button
          type="button"
          onClick={handleDelete}
          className="text-xs px-2 py-1 bg-red-900 hover:bg-red-800 rounded text-white"
        >
          Delete
        </button>
      </div>

      {last_error && (
        <div className="text-xs text-red-400 bg-red-950 border border-red-900 rounded p-2">
          Last generation error: {last_error}
        </div>
      )}

      {/* Approved content */}
      {hasContent && !hasDraft && (
        <section>
          <h3 className="text-xs uppercase tracking-wider text-gray-400 mb-1">
            Approved content
          </h3>
          <XmlDocument content={node.content} renderers={referencesRenderers} />
        </section>
      )}

      {/* Pending draft */}
      {hasDraft && pending_draft && (
        <section>
          <h3 className="text-xs uppercase tracking-wider text-gray-400 mb-1">
            Pending draft
          </h3>
          <XmlDocument
            content={pending_draft.content}
            renderers={referencesRenderers}
          />
          <div className="flex gap-2 mt-2">
            <button
              type="button"
              disabled={approveMutation.isPending}
              onClick={handleApprove}
              className="text-xs px-3 py-1 bg-green-700 hover:bg-green-600 disabled:opacity-40 rounded text-white"
            >
              Approve
            </button>
            <button
              type="button"
              disabled={discardMutation.isPending}
              onClick={handleDiscard}
              className="text-xs px-3 py-1 bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded text-white"
            >
              Discard
            </button>
          </div>
        </section>
      )}

      {/* Feedback / regenerate */}
      <section>
        <h3 className="text-xs uppercase tracking-wider text-gray-400 mb-1">
          {hasContent ? 'Request update' : 'Feedback'}
        </h3>
        <textarea
          className="w-full px-2 py-1 bg-gray-950 border border-gray-700 rounded text-sm text-gray-100"
          rows={3}
          value={feedbackText}
          onChange={(e) => setFeedbackText(e.target.value)}
          placeholder="Optional prose feedback. Leave empty to regenerate from scratch."
        />
        <div className="flex items-center gap-2 mt-2">
          <button
            type="button"
            disabled={isRunning || updateMutation.isPending}
            onClick={handleFeedback}
            className="text-xs px-3 py-1 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 rounded text-white"
          >
            {isRunning
              ? 'Generation running…'
              : hasContent
                ? 'Update'
                : 'Regenerate'}
          </button>
          {hasContent && !hasDraft && (
            <span className="text-xs text-gray-500 italic">
              References stay editable after approval — feedback
              always reopens the draft cycle.
            </span>
          )}
        </div>
      </section>

      {/* Connected nodes */}
      <section>
        <h3 className="text-xs uppercase tracking-wider text-gray-400 mb-1">
          Outgoing reference edges
        </h3>
        {data.outgoing_edges.length === 0 ? (
          <div className="text-xs text-gray-500 italic">
            This reference does not point at any other node.
          </div>
        ) : (
          <ul className="space-y-1">
            {data.outgoing_edges.map((edge) => (
              <li
                key={edge.edge_id}
                className="flex items-center justify-between bg-gray-800/40 border border-gray-700 rounded px-2 py-1"
              >
                <span className="text-xs font-mono text-blue-300">
                  → {edge.target_id}
                </span>
                <button
                  type="button"
                  onClick={() =>
                    removeEdgeMutation.mutate({
                      sourceId: edge.source_id,
                      targetId: edge.target_id,
                    })
                  }
                  className="text-xs px-2 py-0.5 bg-gray-700 hover:bg-red-800 rounded text-white"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}

        <h3 className="text-xs uppercase tracking-wider text-gray-400 mt-3 mb-1">
          Incoming reference edges
        </h3>
        {data.incoming_edges.length === 0 ? (
          <div className="text-xs text-gray-500 italic">
            No other nodes currently pull this reference into their
            regen context.
          </div>
        ) : (
          <ul className="space-y-1">
            {data.incoming_edges.map((edge) => (
              <li
                key={edge.edge_id}
                className="text-xs font-mono text-gray-400 bg-gray-800/40 border border-gray-700 rounded px-2 py-1"
              >
                {edge.source_id} →
              </li>
            ))}
          </ul>
        )}
      </section>

      {latest_telemetry && (
        <section className="text-xs text-gray-500">
          Latest generation: {latest_telemetry.prompt_tokens} prompt /{' '}
          {latest_telemetry.completion_tokens} completion tokens (
          {latest_telemetry.model})
        </section>
      )}
    </div>
  );
}
