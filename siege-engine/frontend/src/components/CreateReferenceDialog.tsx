import { useState } from 'react';
import { useCreateReferenceMutation } from '../hooks/mutations/useReferenceMutations';

interface Props {
  projectId: string;
  /** Optional pre-filled related nodes. Populated when the dialog
   * is opened from a feature / component / policy detail page. */
  initialRelatedNodes?: string[];
  onClose: () => void;
  onCreated?: (refId: string) => void;
}

/**
 * Modal dialog for creating a new reference via the LLM-assisted
 * generation flow. The user supplies a name + a prose
 * seed_description + an optional list of related_nodes (node ids
 * the ref should reference); the backend mints a ref_* node,
 * wires up the reference edges, and enqueues a generation job.
 *
 * Unlike the vocab dialog (which submits user-authored XML), the
 * ref dialog does NOT ask the user to hand-write the body — the
 * LLM writes the initial content from the seed_description, and
 * the user iterates via the Feedback → Regen loop on the panel.
 */
export function CreateReferenceDialog({
  projectId,
  initialRelatedNodes = [],
  onClose,
  onCreated,
}: Props) {
  const [name, setName] = useState('');
  const [seedDescription, setSeedDescription] = useState('');
  const [relatedNodesText, setRelatedNodesText] = useState(
    initialRelatedNodes.join(', '),
  );

  const createMutation = useCreateReferenceMutation(projectId);

  const canSubmit =
    name.trim().length > 0 && seedDescription.trim().length > 0;

  const handleSubmit = () => {
    const relatedNodes = relatedNodesText
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    createMutation.mutate(
      {
        name: name.trim(),
        seedDescription: seedDescription.trim(),
        relatedNodes,
      },
      {
        onSuccess: (result) => {
          onCreated?.(result.ref_id);
          onClose();
        },
      },
    );
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      role="dialog"
      aria-label="Create reference"
    >
      <div className="bg-gray-900 border border-gray-700 rounded p-6 w-full max-w-lg space-y-4">
        <h2 className="text-sm font-bold text-white">Add reference</h2>

        <label className="block space-y-1">
          <div className="text-xs uppercase tracking-wider text-gray-400">
            Title
          </div>
          <input
            type="text"
            className="w-full px-2 py-1 bg-gray-950 border border-gray-700 rounded text-sm text-gray-100"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Deployment runbook"
          />
        </label>

        <label className="block space-y-1">
          <div className="text-xs uppercase tracking-wider text-gray-400">
            Seed description
          </div>
          <textarea
            className="w-full px-2 py-1 bg-gray-950 border border-gray-700 rounded text-sm text-gray-100"
            rows={4}
            value={seedDescription}
            onChange={(e) => setSeedDescription(e.target.value)}
            placeholder="Short prose describing what this reference should cover — e.g. 'step-by-step deployment runbook for the billing service'."
          />
        </label>

        <label className="block space-y-1">
          <div className="text-xs uppercase tracking-wider text-gray-400">
            Related node IDs (optional, comma-separated)
          </div>
          <input
            type="text"
            className="w-full px-2 py-1 bg-gray-950 border border-gray-700 rounded text-sm text-gray-100 font-mono"
            value={relatedNodesText}
            onChange={(e) => setRelatedNodesText(e.target.value)}
            placeholder="comp_XXXXXXXX, feat_YYYYYYYY"
          />
          <p className="text-xs text-gray-500">
            Each related node receives an outgoing <code>reference</code>{' '}
            edge from this ref, which makes the ref's content visible
            to that node's regen context.
          </p>
        </label>

        {createMutation.isError && (
          <div className="text-xs text-red-400">
            {String(createMutation.error ?? 'Create failed')}
          </div>
        )}

        <div className="flex gap-2 justify-end">
          <button
            type="button"
            className="text-xs px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-white"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!canSubmit || createMutation.isPending}
            className="text-xs px-3 py-1 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 rounded text-white"
            onClick={handleSubmit}
          >
            {createMutation.isPending ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}
