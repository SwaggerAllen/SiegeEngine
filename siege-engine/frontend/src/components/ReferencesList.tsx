import { useState } from 'react';
import { useProjectReferences } from '../hooks/queries/useReferenceQueries';
import { ReferencePanel } from './ReferencePanel';

interface Props {
  projectId: string;
}

/**
 * Project references list view (read-only).
 *
 * Split-pane: left side lists every `ref_*` node in the
 * project; right side shows the selected ref's panel (approved
 * content + edge relationships). Authoring happens in Claude
 * Code via the `/create_ref` skill — the dashboard is a projection.
 */
export function ReferencesList({ projectId }: Props) {
  const { data, isLoading, error } = useProjectReferences(projectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);

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
        <h2 className="text-sm font-bold text-white mb-4">References</h2>

        {refs.length === 0 && (
          <p className="text-sm text-gray-500 italic">
            No references defined yet. Run{' '}
            <code className="text-gray-300">/create_ref</code> in
            Claude Code to add a supplemental document (runbook,
            DSL spec, cross-component invariant). Any node that
            draws a <code>reference</code> edge at a ref pulls its
            content into its regen context.
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
                      (not yet populated)
                    </span>
                  )}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="w-1/2 overflow-auto">
        <ReferencePanel projectId={projectId} refId={selectedId} />
      </div>
    </div>
  );
}
