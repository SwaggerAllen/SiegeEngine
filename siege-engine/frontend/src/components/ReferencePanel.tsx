import { useReferenceDetail } from '../hooks/queries/useReferenceQueries';
import { XmlDocument } from './xml/XmlDocument';
import { referencesRenderers } from './xml/referencesRenderers';

interface Props {
  projectId: string;
  refId: string | null;
}

/**
 * Read-only detail panel for a single reference.
 *
 * Refs are now authored in Claude Code via the `/create_ref` skill —
 * the dashboard surfaces approved content + edge relationships but
 * does not write. Use the CLI / skill to add or update entries.
 */
export function ReferencePanel({ projectId, refId }: Props) {
  const { data, isLoading, error } = useReferenceDetail(projectId, refId);

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

  const { node } = data;
  const hasContent = !!node.content;

  return (
    <div className="space-y-4 p-4">
      <div>
        <h2 className="text-base font-bold text-white m-0">{node.name}</h2>
        <div className="text-xs font-mono text-gray-500">{node.id}</div>
      </div>

      <section>
        <h3 className="text-xs uppercase tracking-wider text-gray-400 mb-1">
          Content
        </h3>
        {hasContent ? (
          <XmlDocument content={node.content} renderers={referencesRenderers} />
        ) : (
          <div className="text-xs text-gray-500 italic">
            No content yet.
          </div>
        )}
      </section>

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
                className="bg-gray-800/40 border border-gray-700 rounded px-2 py-1"
              >
                <span className="text-xs font-mono text-blue-300">
                  → {edge.target_id}
                </span>
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

      <section className="text-xs text-gray-500 italic border-t border-gray-800 pt-3">
        References are authored in Claude Code via the{' '}
        <code className="text-gray-300">/create_ref</code> skill. The
        dashboard shows the projected state — edit the body file in the
        project repo to change it.
      </section>
    </div>
  );
}
