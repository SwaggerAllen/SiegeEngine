import { useState } from 'react';
import { useProjectReferences } from '../hooks/queries/useReferenceQueries';
import { CreateReferenceDialog } from './CreateReferenceDialog';
import { ReferencePanel } from './ReferencePanel';

interface Props {
  projectId: string;
}

/**
 * Project references list view (Phase 6.6).
 *
 * Split-pane: left side lists every ``ref_*`` node in the
 * project; right side shows the selected ref's panel (approved
 * content or pending draft, plus feedback / approve / discard /
 * delete / edge editing). A "+ Add reference" button opens the
 * creation dialog.
 */
export function ReferencesList({ projectId }: Props) {
  const { data, isLoading, error } = useProjectReferences(projectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  if (isLoading) {
    return <div className="p-6 text-gray-400 text-sm">Loading references…</div>;
  }
  if (error) {
    return (
      <div className="p-6 text-red-400 text-sm">Failed to load references.</div>
    );
  }

  const refs = data?.references ?? [];

  return (
    <div className="flex h-full">
      <div className="w-1/2 overflow-auto border-r border-gray-800 p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-bold text-white">References</h2>
          <button
            type="button"
            className="text-xs px-3 py-1 bg-blue-700 hover:bg-blue-600 rounded text-white"
            onClick={() => setDialogOpen(true)}
          >
            + Add reference
          </button>
        </div>

        {refs.length === 0 && (
          <p className="text-sm text-gray-500 italic">
            No references defined yet. Use "+ Add reference" to
            attach supplemental documents (runbooks, DSL specs,
            cross-component invariants) to nodes. Any node that
            draws a <code>reference</code> edge at a ref pulls
            its content into its regen context.
          </p>
        )}

        <ul className="space-y-1">
          {refs.map((ref) => (
            <li key={ref.id}>
              <button
                type="button"
                onClick={() => setSelectedId(ref.id)}
                className={`w-full text-left px-2 py-1 rounded text-sm ${
                  selectedId === ref.id
                    ? 'bg-blue-900 text-white'
                    : 'text-gray-300 hover:bg-gray-800'
                }`}
              >
                <div className="font-semibold">{ref.name}</div>
                <div className="text-xs text-gray-500 font-mono">
                  {ref.id}
                  {!ref.has_content && (
                    <span className="ml-2 italic text-yellow-500">
                      (not yet approved)
                    </span>
                  )}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="w-1/2 overflow-auto">
        <ReferencePanel
          projectId={projectId}
          refId={selectedId}
          onDeleted={() => setSelectedId(null)}
        />
      </div>

      {dialogOpen && (
        <CreateReferenceDialog
          projectId={projectId}
          onClose={() => setDialogOpen(false)}
          onCreated={(id) => setSelectedId(id)}
        />
      )}
    </div>
  );
}
