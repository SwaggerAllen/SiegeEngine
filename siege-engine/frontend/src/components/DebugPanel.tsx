import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { type DebugSnapshot, getDebugSnapshot } from '../api/debug';

/**
 * Debug snapshot panel — single-shot dump of the project's
 * full state plus the most recent events and jobs. The
 * "Copy snapshot" button puts the entire blob (formatted JSON)
 * on the clipboard so the user can paste it into a bug report
 * or back to a maintainer.
 *
 * Sections render as collapsible blocks: a one-line summary
 * always visible, click to expand the table. Events and jobs
 * are reverse-chronological so the most-recent activity sits
 * at the top.
 */
export function DebugPanel({ projectId }: { projectId: string }) {
  const { data, error, isLoading, refetch, isFetching } = useQuery<DebugSnapshot>({
    queryKey: ['debug-snapshot', projectId],
    queryFn: () => getDebugSnapshot(projectId),
  });

  const [copied, setCopied] = useState(false);
  const blob = useMemo(() => (data ? JSON.stringify(data, null, 2) : ''), [data]);

  const handleCopy = () => {
    if (!blob) return;
    navigator.clipboard.writeText(blob).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  if (isLoading) {
    return <div className="p-6 text-gray-400 text-sm">Loading snapshot…</div>;
  }
  if (error || !data) {
    const message = error instanceof Error ? error.message : String(error);
    return (
      <div className="p-6 text-red-400 text-sm">
        Failed to load snapshot: {message || 'unknown error'}
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <header className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-lg font-semibold">Debug Snapshot</h2>
        <span className="text-xs text-gray-500">
          {data.project.name} · <span className="font-mono">{data.project.id}</span>
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="px-3 py-1 text-xs rounded border border-gray-700 text-gray-300 hover:bg-gray-800 disabled:opacity-40"
          >
            {isFetching ? 'Refreshing…' : 'Refresh'}
          </button>
          <button
            type="button"
            onClick={handleCopy}
            className="px-3 py-1 text-xs rounded bg-blue-700 hover:bg-blue-600 text-white"
            data-testid="debug-copy-button"
          >
            {copied ? 'Copied' : 'Copy snapshot'}
          </button>
        </div>
      </header>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <Stat label="Nodes" value={data.summary.node_count} />
        <Stat label="Edges" value={data.summary.edge_count} />
        <Stat label="Fragments" value={data.summary.fragment_count} />
        <Stat label="Drafts" value={data.summary.draft_count} />
        <Stat label="Staleness" value={data.summary.staleness_rows} />
        <Stat label="Recent jobs" value={data.summary.jobs_returned} />
        <Stat label="Recent events" value={data.summary.events_returned} />
      </div>

      <Section
        title={`Nodes (${data.nodes.length})`}
        rows={data.nodes}
        defaultOpen={false}
        primaryColumns={['id', 'tier', 'kind', 'name', 'parent_id', 'content_length']}
      />
      <Section
        title={`Edges (${data.edges.length})`}
        rows={data.edges}
        defaultOpen={false}
        primaryColumns={['id', 'edge_type', 'source_id', 'target_id']}
      />
      <Section
        title={`Drafts (${data.drafts.length})`}
        rows={data.drafts}
        defaultOpen={false}
        primaryColumns={['id', 'target_id', 'status', 'discard_reason', 'content_length']}
      />
      <Section
        title={`Staleness ledger (${data.staleness.length})`}
        rows={data.staleness}
        defaultOpen={false}
        primaryColumns={[
          'stale_node_id',
          'upstream_node_id',
          'trigger_event_offset',
          'trigger_reason',
        ]}
      />
      <Section
        title={`Recent jobs (${data.recent_jobs.length})`}
        rows={data.recent_jobs}
        defaultOpen={true}
        primaryColumns={[
          'created_at',
          'job_type',
          'status',
          'retry_count',
          'error_message',
          'is_deferred',
        ]}
      />
      <Section
        title={`Recent events (${data.recent_events.length})`}
        rows={data.recent_events}
        defaultOpen={true}
        primaryColumns={['offset', 'event_type', 'created_at']}
      />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-gray-800 bg-gray-900/40 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-gray-500">{label}</div>
      <div className="text-base font-mono text-gray-100 tabular-nums">{value}</div>
    </div>
  );
}

function Section({
  title,
  rows,
  primaryColumns,
  defaultOpen,
}: {
  title: string;
  rows: Array<Record<string, unknown>>;
  primaryColumns: string[];
  defaultOpen: boolean;
}) {
  return (
    <details
      className="border border-gray-800 rounded bg-gray-950/40"
      open={defaultOpen}
    >
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-gray-200 hover:bg-gray-900/40">
        {title}
      </summary>
      {rows.length === 0 ? (
        <div className="px-3 py-2 text-xs text-gray-500 italic">No rows.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px] font-mono">
            <thead className="bg-gray-900/40 text-gray-500 text-left">
              <tr>
                {primaryColumns.map((col) => (
                  <th key={col} className="px-3 py-1 font-normal">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => (
                <tr key={idx} className="border-t border-gray-800/60">
                  {primaryColumns.map((col) => (
                    <td key={col} className="px-3 py-1 align-top text-gray-300 whitespace-nowrap">
                      {renderCell(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

function renderCell(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') return String(v);
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}
