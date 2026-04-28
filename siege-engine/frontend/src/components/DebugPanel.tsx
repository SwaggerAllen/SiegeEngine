import { useQuery } from '@tanstack/react-query';
import { type MouseEvent, useMemo, useState } from 'react';
import { type DebugSnapshot, getDebugSnapshot } from '../api/debug';

/**
 * Debug snapshot panel — single-shot dump of the project's
 * full state plus the most recent events and jobs.
 *
 * Pasting the full blob can blow past a chat client's input
 * limit, so the panel surfaces character counts everywhere and
 * exposes per-section + chunked copy buttons. The chunk size
 * input controls how aggressively oversized sections get split.
 */
const DEFAULT_CHUNK_SIZE = 50000;
const MIN_CHUNK_SIZE = 1000;

type SnapshotKey = keyof DebugSnapshot;

export function DebugPanel({ projectId }: { projectId: string }) {
  const { data, error, isLoading, refetch, isFetching } = useQuery<DebugSnapshot>({
    queryKey: ['debug-snapshot', projectId],
    queryFn: () => getDebugSnapshot(projectId),
  });

  const [chunkSize, setChunkSize] = useState(DEFAULT_CHUNK_SIZE);
  const blob = useMemo(() => (data ? JSON.stringify(data, null, 2) : ''), [data]);

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
          <CopyButton
            label="Copy full snapshot"
            payload={blob}
            testId="debug-copy-button"
            variant="primary"
          />
        </div>
      </header>

      <div
        className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-gray-400 border border-gray-800 rounded bg-gray-950/40 px-3 py-2"
        data-testid="debug-copy-controls"
      >
        <span>
          Full snapshot:{' '}
          <span className="font-mono text-gray-200" data-testid="debug-total-chars">
            {blob.length.toLocaleString()}
          </span>{' '}
          chars
        </span>
        <label className="flex items-center gap-1">
          Chunk size:
          <input
            type="number"
            value={chunkSize}
            min={MIN_CHUNK_SIZE}
            step={1000}
            onChange={(e) => {
              const next = Number(e.target.value);
              setChunkSize(
                Number.isFinite(next) && next >= MIN_CHUNK_SIZE ? next : MIN_CHUNK_SIZE,
              );
            }}
            className="w-24 bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-xs font-mono text-gray-200"
            data-testid="debug-chunk-size-input"
          />
          <span className="text-gray-500">chars/chunk</span>
        </label>
        <span className="text-gray-500">
          Sections larger than this expose per-chunk copy buttons.
        </span>
      </div>

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
        sectionKey="nodes"
        title="Nodes"
        rows={data.nodes}
        defaultOpen={false}
        primaryColumns={['id', 'tier', 'kind', 'name', 'parent_id', 'content_length']}
        chunkSize={chunkSize}
      />
      <Section
        sectionKey="edges"
        title="Edges"
        rows={data.edges}
        defaultOpen={false}
        primaryColumns={['id', 'edge_type', 'source_id', 'target_id']}
        chunkSize={chunkSize}
      />
      <Section
        sectionKey="drafts"
        title="Drafts"
        rows={data.drafts}
        defaultOpen={false}
        primaryColumns={['id', 'target_id', 'status', 'discard_reason', 'content_length']}
        chunkSize={chunkSize}
      />
      <Section
        sectionKey="staleness"
        title="Staleness ledger"
        rows={data.staleness}
        defaultOpen={false}
        primaryColumns={['stale_node_id', 'source_node_id', 'source_offset', 'reason']}
        chunkSize={chunkSize}
      />
      <Section
        sectionKey="recent_jobs"
        title="Recent jobs"
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
        chunkSize={chunkSize}
      />
      <Section
        sectionKey="recent_events"
        title="Recent events"
        rows={data.recent_events}
        defaultOpen={true}
        primaryColumns={['offset', 'event_type', 'created_at']}
        chunkSize={chunkSize}
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

function CopyButton({
  label,
  payload,
  testId,
  variant = 'secondary',
}: {
  label: string;
  payload: string;
  testId?: string;
  variant?: 'primary' | 'secondary';
}) {
  const [copied, setCopied] = useState(false);
  const onClick = (e: MouseEvent<HTMLButtonElement>) => {
    // Prevent <details> toggle when this button lives inside a <summary>.
    e.preventDefault();
    e.stopPropagation();
    if (!payload) return;
    navigator.clipboard.writeText(payload).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  const cls =
    variant === 'primary'
      ? 'px-3 py-1 text-xs rounded bg-blue-700 hover:bg-blue-600 text-white'
      : 'px-2 py-0.5 text-[11px] rounded border border-gray-700 text-gray-300 hover:bg-gray-800 font-mono';
  return (
    <button type="button" onClick={onClick} className={cls} data-testid={testId}>
      {copied ? 'Copied' : label}
    </button>
  );
}

type Row = Record<string, unknown>;

function Section({
  sectionKey,
  title,
  rows,
  primaryColumns,
  defaultOpen,
  chunkSize,
}: {
  sectionKey: SnapshotKey | string;
  title: string;
  rows: Row[];
  primaryColumns: string[];
  defaultOpen: boolean;
  chunkSize: number;
}) {
  const sectionPayload = useMemo(
    () => JSON.stringify({ [sectionKey]: rows }, null, 2),
    [sectionKey, rows],
  );
  const charCount = sectionPayload.length;

  const chunks = useMemo(() => {
    if (rows.length === 0 || charCount <= chunkSize) return [];
    return chunkRows(rows, chunkSize);
  }, [rows, charCount, chunkSize]);

  const chunkPayloads = useMemo(
    () =>
      chunks.map((chunk, idx) =>
        JSON.stringify(
          {
            [sectionKey]: chunk,
            _chunk: {
              index: idx + 1,
              total: chunks.length,
              rows_in_chunk: chunk.length,
            },
          },
          null,
          2,
        ),
      ),
    [chunks, sectionKey],
  );

  return (
    <details
      className="border border-gray-800 rounded bg-gray-950/40"
      open={defaultOpen}
    >
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-gray-200 hover:bg-gray-900/40 flex flex-wrap items-center gap-x-3 gap-y-1">
        <span>
          {title} ({rows.length})
        </span>
        <span
          className="text-[11px] text-gray-500 font-mono"
          data-testid={`debug-section-chars-${sectionKey}`}
        >
          {charCount.toLocaleString()} chars
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-1">
          <CopyButton
            label="Copy section"
            payload={sectionPayload}
            testId={`debug-copy-${sectionKey}`}
          />
          {chunkPayloads.map((payload, idx) => (
            <CopyButton
              key={idx}
              label={`${idx + 1}/${chunkPayloads.length} (${payload.length.toLocaleString()})`}
              payload={payload}
              testId={`debug-copy-${sectionKey}-chunk-${idx + 1}`}
            />
          ))}
        </span>
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
                    <td
                      key={col}
                      className="px-3 py-1 align-top text-gray-300 whitespace-nowrap"
                    >
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

// Bin-pack rows into chunks whose JSON-encoded size stays at or below
// maxChars. The size estimate uses each row's standalone stringified
// length plus a couple of bytes for separators — close enough that the
// final chunk JSON we hand to the clipboard still respects the budget
// for any non-pathological row.
function chunkRows<T>(rows: T[], maxChars: number): T[][] {
  if (rows.length === 0) return [];
  const overhead = 80; // wrapper braces + key + _chunk metadata
  const chunks: T[][] = [];
  let current: T[] = [];
  let currentSize = overhead;
  for (const row of rows) {
    const rowSize = JSON.stringify(row, null, 2).length + 4;
    if (current.length > 0 && currentSize + rowSize > maxChars) {
      chunks.push(current);
      current = [];
      currentSize = overhead;
    }
    current.push(row);
    currentSize += rowSize;
  }
  if (current.length > 0) chunks.push(current);
  return chunks;
}

function renderCell(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') return String(v);
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}
