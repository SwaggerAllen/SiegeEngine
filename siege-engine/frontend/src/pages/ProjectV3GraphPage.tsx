import { Link, useParams } from 'react-router-dom';
import { useProjectGraph } from '../hooks/queries/useProjectGraph';
import { useProject } from '../hooks/queries/useProjectQueries';
import { describeApiError } from '../lib/describeApiError';

/**
 * Read-only viewer for the new /siege/api/get-project-graph projection.
 *
 * The dashboard's main project page still reads from the legacy SQL
 * backend, which is empty for upload-imported projects. This page is
 * the bridge: hits the new endpoint directly so the v3 substrate
 * actually shows up in the UI. Surfaces the same {nodes, edges} shape
 * the future graph viz will consume, plus a raw-JSON dump for poking.
 */
export function ProjectV3GraphPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = id ?? '';
  const { data: project } = useProject(projectId);
  const { data, isLoading, error } = useProjectGraph(projectId);

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <header className="border-b border-gray-700 px-6 py-4 flex items-center gap-4">
        <Link to={`/projects/${projectId}`} className="text-gray-400 hover:text-white text-sm">
          &larr; Back to project
        </Link>
        <span className="text-gray-500">/</span>
        <span className="text-sm">v3 graph projection</span>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">{project?.name ?? '…'}</h1>
          <p className="text-sm text-gray-400 mt-1">
            Read-only view from <code>/siege/api/get-project-graph</code>. The dashboard's main
            project page reads from the legacy backend (empty for upload-imported projects); this
            page reads from the git substrate directly.
          </p>
        </div>

        {isLoading && <p className="text-gray-400">Loading…</p>}
        {error != null && (
          <p className="text-red-400 text-sm">{describeApiError(error, 'Failed to load graph')}</p>
        )}
        {data && <GraphView data={data} />}
      </main>
    </div>
  );
}

function GraphView({
  data,
}: {
  data: { ref: string; ref_head_sha: string; nodes: V3Node[]; edges: V3Edge[] };
}) {
  const kindCounts = data.nodes.reduce<Record<string, number>>((acc, n) => {
    acc[n.kind] = (acc[n.kind] ?? 0) + 1;
    return acc;
  }, {});
  const edgeTypeCounts = data.edges.reduce<Record<string, number>>((acc, e) => {
    acc[e.type] = (acc[e.type] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <section className="rounded border border-gray-700 bg-gray-800/50 p-4 text-sm">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Stat label="Ref" value={`${data.ref} @ ${data.ref_head_sha.slice(0, 8)}`} />
          <Stat label="Nodes" value={String(data.nodes.length)} />
          <Stat label="Edges" value={String(data.edges.length)} />
          <Stat
            label="Kinds"
            value={
              Object.entries(kindCounts)
                .map(([k, n]) => `${k}: ${n}`)
                .join(', ') || '—'
            }
          />
        </div>
        <div className="mt-3 text-xs text-gray-400">
          edges:{' '}
          {Object.entries(edgeTypeCounts)
            .map(([t, n]) => `${t}: ${n}`)
            .join(', ') || '—'}
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold mb-2">Nodes</h2>
        <div className="overflow-x-auto rounded border border-gray-700">
          <table className="w-full text-sm">
            <thead className="bg-gray-800 text-gray-300">
              <tr>
                <Th>name</Th>
                <Th>kind</Th>
                <Th>tier</Th>
                <Th>parent</Th>
                <Th>status</Th>
                <Th>score</Th>
                <Th>flags</Th>
                <Th>id</Th>
              </tr>
            </thead>
            <tbody>
              {data.nodes.map((n) => (
                <tr key={n.id} className="border-t border-gray-700/50">
                  <Td>{n.name || <span className="text-gray-500">—</span>}</Td>
                  <Td>{n.kind}</Td>
                  <Td className="text-xs text-gray-400">{n.tier}</Td>
                  <Td className="text-xs text-gray-400">{n.parent_id ?? '—'}</Td>
                  <Td>
                    <StatusPill status={n.status} />
                  </Td>
                  <Td>{n.score ?? '—'}</Td>
                  <Td className="text-xs text-gray-400">
                    {[n.is_foundation && 'foundation', n.implicit && 'implicit']
                      .filter(Boolean)
                      .join(', ') || '—'}
                  </Td>
                  <Td className="font-mono text-xs text-gray-400">{n.id}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold mb-2">Edges</h2>
        <div className="overflow-x-auto rounded border border-gray-700">
          <table className="w-full text-sm">
            <thead className="bg-gray-800 text-gray-300">
              <tr>
                <Th>type</Th>
                <Th>source</Th>
                <Th>target</Th>
              </tr>
            </thead>
            <tbody>
              {data.edges.map((e) => (
                <tr key={e.id} className="border-t border-gray-700/50">
                  <Td>{e.type}</Td>
                  <Td className="font-mono text-xs text-gray-400">{e.source_id}</Td>
                  <Td className="font-mono text-xs text-gray-400">{e.target_id}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <details className="rounded border border-gray-700 bg-gray-800/30 p-3">
        <summary className="cursor-pointer text-sm text-gray-300">Raw JSON</summary>
        <pre className="mt-2 max-h-96 overflow-auto text-xs text-gray-200">
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className="mt-0.5 text-gray-100">{value}</div>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="text-left px-3 py-2 font-medium">{children}</th>;
}

function Td({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <td className={`px-3 py-1.5 ${className}`}>{children}</td>;
}

function StatusPill({ status }: { status: string }) {
  const color =
    status === 'approved'
      ? 'bg-green-900/60 text-green-200'
      : status === 'reviewed'
        ? 'bg-blue-900/60 text-blue-200'
        : status === 'drafted'
          ? 'bg-amber-900/60 text-amber-200'
          : 'bg-gray-700/60 text-gray-300';
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-xs ${color}`}>{status}</span>
  );
}

// Re-export the types here so the file is self-contained; the source
// of truth still lives in `api/siege.ts`.
type V3Node = import('../api/siege').V3Node;
type V3Edge = import('../api/siege').V3Edge;
