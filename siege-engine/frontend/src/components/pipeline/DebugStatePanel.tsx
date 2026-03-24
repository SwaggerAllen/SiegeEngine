import { useEffect, useState, useCallback, useRef } from 'react';
import { getDebugState } from '../../api/pipeline';
import { usePipelineStore } from '../../store/pipelineStore';
import { useDAGStore } from '../../store/dagStore';
import { useProjectStore } from '../../store/projectStore';
import { useAuthStore } from '../../store/authStore';
import { useErrorLogStore } from '../../store/errorLogStore';
import { getRecordedSnapshots, clearRecordedSnapshots } from '../../lib/snapshotRecorder';
import { getDebugLog, clearDebugLog, type DebugEntry } from '../../lib/debugLog';

interface DebugState {
  snapshot: Record<string, unknown>;
  runs: Array<Record<string, unknown>>;
  executions: Array<Record<string, unknown>>;
  artifacts: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
  jobs: Array<Record<string, unknown>>;
  mismatches: Array<Record<string, unknown>>;
}

function shortId(id: string | null | undefined): string {
  if (!id) return '(none)';
  return id.length > 12 ? id.slice(0, 8) : id;
}

function ts(iso: string | null | undefined): string {
  if (!iso) return '---';
  const d = new Date(iso);
  const h = d.getUTCHours().toString().padStart(2, '0');
  const m = d.getUTCMinutes().toString().padStart(2, '0');
  const s = d.getUTCSeconds().toString().padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function pad(s: string, len: number): string {
  return s.padEnd(len);
}

function formatDebugText(state: DebugState): string {
  const lines: string[] = [];

  // Mismatches (top if any)
  if (state.mismatches.length > 0) {
    lines.push('!!! PROJECTION DRIFT DETECTED (snapshot is source of truth) !!!');
    for (const m of state.mismatches) {
      if (m.type === 'artifact_status') {
        lines.push(`  ARTIFACT ${m.name} (${shortId(m.id as string)}): snapshot=${m.snapshot}  db=${m.db}`);
      } else {
        lines.push(`  STAGE ${m.key}: snapshot=${m.snapshot}  db=${m.db}`);
      }
    }
    lines.push('');
  }

  // Snapshot
  const snap = state.snapshot;
  lines.push('=== SNAPSHOT ===');
  lines.push(`is_running: ${snap.is_running} | is_paused: ${snap.is_paused} | current_run_id: ${shortId(snap.current_run_id as string)} | last_seq: ${snap.last_sequence}`);
  if (snap.paused_stage) lines.push(`paused_stage: ${snap.paused_stage}`);

  const runStatus = snap.run_status as Record<string, string>;
  if (Object.keys(runStatus).length > 0) {
    lines.push(`run_status:`);
    for (const [rid, status] of Object.entries(runStatus)) {
      lines.push(`  ${shortId(rid)}: ${status}`);
    }
  }

  const stageStatuses = snap.stage_statuses as Record<string, string>;
  if (Object.keys(stageStatuses).length > 0) {
    lines.push(`stage_statuses:`);
    for (const [key, status] of Object.entries(stageStatuses)) {
      lines.push(`  ${pad(key, 40)} ${status}`);
    }
  }

  const artifactStatuses = snap.artifact_statuses as Record<string, string>;
  if (Object.keys(artifactStatuses).length > 0) {
    lines.push(`artifact_statuses:`);
    // Build name lookup from artifacts
    const nameMap: Record<string, string> = {};
    for (const a of state.artifacts) {
      nameMap[a.id as string] = a.name as string;
    }
    for (const [aid, status] of Object.entries(artifactStatuses)) {
      const name = nameMap[aid] || shortId(aid);
      lines.push(`  ${pad(name, 30)} ${pad(status, 18)} (${shortId(aid)})`);
    }
  }

  const stageErrors = snap.stage_errors as Record<string, unknown> | undefined;
  if (stageErrors && Object.keys(stageErrors).length > 0) {
    lines.push(`stage_errors:`);
    for (const [key, err] of Object.entries(stageErrors)) {
      if (err && typeof err === 'object') {
        const obj = err as Record<string, unknown>;
        const errMsg = obj.error || '(no message)';
        const retries = obj.retry_count != null ? ` (retries: ${obj.retry_count})` : '';
        lines.push(`  ${key}: ${errMsg}${retries}`);
      } else {
        lines.push(`  ${key}: ${err}`);
      }
    }
  }

  const stageTriggers = snap.stage_triggers as Record<string, string>;
  if (Object.keys(stageTriggers).length > 0) {
    lines.push(`stage_triggers:`);
    for (const [key, trigger] of Object.entries(stageTriggers)) {
      lines.push(`  ${key}: ${trigger}`);
    }
  }

  const executionMap = snap.execution_map as Record<string, Record<string, string>>;
  if (executionMap && Object.keys(executionMap).length > 0) {
    lines.push(`execution_map:`);
    for (const [key, entry] of Object.entries(executionMap)) {
      const execId = shortId(entry?.execution_id);
      const artId = entry?.artifact_id ? shortId(entry.artifact_id) : '(none)';
      lines.push(`  ${pad(key, 40)} -> exec=${execId}  art=${artId}`);
    }
  }

  const artifactMeta = snap.artifact_meta as Record<string, Record<string, string>>;
  if (artifactMeta && Object.keys(artifactMeta).length > 0) {
    lines.push(`artifact_meta:`);
    for (const [aid, meta] of Object.entries(artifactMeta)) {
      const name = meta?.name || '?';
      const type = meta?.type || '?';
      const ck = meta?.component_key || '';
      lines.push(`  ${pad(name, 25)} type=${pad(type, 22)} comp=${ck || '(none)'}  (${shortId(aid)})`);
    }
  }

  lines.push('');

  // Runs (backend caps at most recent 20)
  lines.push(`=== RUNS (showing ${state.runs.length}) ===`);
  for (const r of state.runs) {
    const parts = [
      `#${r.run_number}`,
      `run_id=${shortId(r.run_id as string)}`,
      `status=${pad(r.status as string, 10)}`,
      `${ts(r.started_at as string)} -> ${ts(r.completed_at as string)}`,
    ];
    if (r.propagation_run) parts.push('PROPAGATION');
    if (r.start_stage_key) parts.push(`from=${r.start_stage_key}${r.start_component_key ? ':' + r.start_component_key : ''}`);
    parts.push(`loops=${r.ai_loops}`);
    parts.push(`stop=${r.stop_point}`);
    lines.push(parts.join(' | '));
  }
  lines.push('');

  // Executions (backend caps at most recent 40)
  lines.push(`=== EXECUTIONS (showing ${state.executions.length}) ===`);
  // Build artifact name lookup
  const artNameMap: Record<string, string> = {};
  for (const a of state.artifacts) {
    artNameMap[a.id as string] = (a.name as string).slice(0, 20);
  }
  for (const e of state.executions) {
    const stageLabel = e.component_key
      ? `${e.stage_key}:${e.component_key}`
      : e.stage_key as string;
    const artLabel = e.artifact_id
      ? (artNameMap[e.artifact_id as string] || shortId(e.artifact_id as string))
      : '(no artifact)';
    let line = `${shortId(e.id as string)} | ${pad(stageLabel, 35)} | ${pad(e.status as string, 16)} | art=${pad(artLabel, 20)} | run=${shortId(e.run_id as string)} | ${ts(e.started_at as string)}->${ts(e.completed_at as string)}`;
    if (e.error_message) line += ` | err="${e.error_message}"`;
    if ((e.retry_count as number) > 0) line += ` | retries=${e.retry_count}`;
    lines.push(line);
  }
  lines.push('');

  // Artifacts
  lines.push(`=== ARTIFACTS (${state.artifacts.length}) ===`);
  for (const a of state.artifacts) {
    const parts = [
      shortId(a.id as string),
      pad(a.name as string, 25),
      pad(a.status as string, 16),
      `v${a.version}`,
      `${a.content_length} chars`,
    ];
    if (a.file_path) parts.push(`file=${a.file_path}`);
    if (a.git_commit_sha) parts.push(`sha=${shortId(a.git_commit_sha as string)}`);
    lines.push(parts.join(' | '));
  }
  lines.push('');

  // Events
  lines.push(`=== RECENT EVENTS (last ${state.events.length}) ===`);
  for (const ev of state.events) {
    const payload = JSON.stringify(ev.payload);
    const payloadShort = payload.length > 100 ? payload.slice(0, 100) + '...' : payload;
    lines.push(`seq=${String(ev.sequence).padStart(4)} | ${pad(ev.event_type as string, 22)} | run=${shortId(ev.run_id as string)} | ${ts(ev.created_at as string)} | ${payloadShort}`);
  }
  lines.push('');

  // Jobs
  lines.push(`=== ACTIVE JOBS (${state.jobs.length}) ===`);
  if (state.jobs.length === 0) {
    lines.push('(none)');
  } else {
    for (const j of state.jobs) {
      lines.push(`${shortId(j.id as string)} | ${j.job_type} | ${j.status} | ${JSON.stringify(j.payload)}`);
    }
  }

  return lines.join('\n');
}

type SubTab = 'backend' | 'frontend' | 'errors' | 'log';

export function DebugStatePanel({ projectId }: { projectId: string }) {
  const errorCount = useErrorLogStore((s) => s.errors.length);
  const [subTab, setSubTab] = useState<SubTab>('backend');
  const [state, setState] = useState<DebugState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const fetchState = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getDebugState(projectId);
      setState(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch debug state');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchState();
  }, [fetchState]);

  const debugText = state ? formatDebugText(state) : '';

  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="h-full flex flex-col p-4 gap-3">
      <div className="flex items-center justify-between shrink-0">
        <h2 className="text-lg font-bold text-white">Debug State</h2>
        <div className="flex items-center gap-2">
          {subTab === 'backend' && (
            <button
              onClick={fetchState}
              disabled={loading}
              className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded disabled:opacity-50"
            >
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          )}
          {subTab === 'backend' && (
            <button
              onClick={() => handleCopy(debugText)}
              className={`px-3 py-1.5 text-white text-xs rounded disabled:opacity-50 ${
                copied ? 'bg-green-600' : 'bg-blue-600 hover:bg-blue-700'
              }`}
            >
              {copied ? 'Copied!' : 'Copy'}
            </button>
          )}
        </div>
      </div>
      <div className="flex rounded overflow-hidden border border-gray-600 self-start shrink-0">
        <button
          onClick={() => setSubTab('backend')}
          className={`px-3 py-1 text-xs ${subTab === 'backend' ? 'bg-gray-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}
        >
          Backend
        </button>
        <button
          onClick={() => setSubTab('frontend')}
          className={`px-3 py-1 text-xs ${subTab === 'frontend' ? 'bg-gray-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}
        >
          Frontend
        </button>
        <button
          onClick={() => setSubTab('errors')}
          className={`px-3 py-1 text-xs ${subTab === 'errors' ? 'bg-gray-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}
        >
          Errors{errorCount > 0 ? ` (${errorCount})` : ''}
        </button>
        <button
          onClick={() => setSubTab('log')}
          className={`px-3 py-1 text-xs ${subTab === 'log' ? 'bg-yellow-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}
        >
          Log
        </button>
      </div>

      {subTab === 'backend' ? (
        <>
          {error && (
            <div className="text-red-400 text-sm bg-red-900/30 border border-red-700 rounded px-3 py-2">
              {error}
            </div>
          )}
          {state && state.mismatches.length > 0 && (
            <div className="text-yellow-300 text-xs bg-yellow-900/30 border border-yellow-700 rounded px-3 py-2 shrink-0">
              {state.mismatches.length} projection drift{state.mismatches.length > 1 ? 's' : ''} detected (snapshot is source of truth)
            </div>
          )}
          <pre className="flex-1 overflow-auto bg-gray-950 border border-gray-700 rounded p-3 text-xs text-gray-300 font-mono whitespace-pre leading-relaxed">
            {debugText || (loading ? 'Loading...' : 'No data')}
          </pre>
        </>
      ) : subTab === 'frontend' ? (
        <ZustandSubTab onCopy={handleCopy} />
      ) : subTab === 'log' ? (
        <DebugLogSubTab onCopy={handleCopy} />
      ) : (
        <ErrorsSubTab />
      )}
    </div>
  );
}

/** Strip functions from state for display, truncate large strings/arrays */
function sanitizeForDisplay(obj: unknown, depth = 0): unknown {
  if (depth > 4) return '(max depth)';
  if (obj === null || obj === undefined) return obj;
  if (typeof obj === 'function') return '(fn)';
  if (typeof obj === 'string') {
    return obj.length > 200 ? obj.slice(0, 200) + `...(${obj.length} chars)` : obj;
  }
  if (typeof obj !== 'object') return obj;
  if (Array.isArray(obj)) {
    if (obj.length > 20) {
      return [
        ...obj.slice(0, 10).map((v) => sanitizeForDisplay(v, depth + 1)),
        `...(${obj.length} items total)`,
      ];
    }
    return obj.map((v) => sanitizeForDisplay(v, depth + 1));
  }
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    out[k] = sanitizeForDisplay(v, depth + 1);
  }
  return out;
}

function grabSnapshot() {
  return {
    pipeline: sanitizeForDisplay(usePipelineStore.getState()),
    dag: sanitizeForDisplay(useDAGStore.getState()),
    project: sanitizeForDisplay(useProjectStore.getState()),
    auth: sanitizeForDisplay(useAuthStore.getState()),
    errors: sanitizeForDisplay(useErrorLogStore.getState()),
  };
}

/** Shallow diff two objects, returning only changed/added/removed keys */
function diffSnapshots(
  prev: Record<string, unknown>,
  next: Record<string, unknown>,
  prefix = '',
): string[] {
  const lines: string[] = [];
  const allKeys = new Set([...Object.keys(prev), ...Object.keys(next)]);
  for (const key of allKeys) {
    const path = prefix ? `${prefix}.${key}` : key;
    const a = prev[key];
    const b = next[key];
    if (a === undefined) {
      lines.push(`+ ${path}: ${JSON.stringify(b)}`);
    } else if (b === undefined) {
      lines.push(`- ${path}: ${JSON.stringify(a)}`);
    } else if (typeof a === 'object' && a !== null && typeof b === 'object' && b !== null && !Array.isArray(a) && !Array.isArray(b)) {
      lines.push(...diffSnapshots(a as Record<string, unknown>, b as Record<string, unknown>, path));
    } else {
      const aStr = JSON.stringify(a);
      const bStr = JSON.stringify(b);
      if (aStr !== bStr) {
        lines.push(`~ ${path}:`);
        lines.push(`    was: ${aStr.length > 200 ? aStr.slice(0, 200) + '...' : aStr}`);
        lines.push(`    now: ${bStr.length > 200 ? bStr.slice(0, 200) + '...' : bStr}`);
      }
    }
  }
  return lines;
}

function ZustandSubTab({ onCopy }: { onCopy: (text: string) => void }) {
  const renderCount = useRef(0);
  renderCount.current += 1;

  const lastSnapshotRef = useRef<Record<string, unknown> | null>(null);
  const [diffText, setDiffText] = useState<string | null>(null);
  const [displaySnapshot, setDisplaySnapshot] = useState<Record<string, unknown> | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [expandedEntry, setExpandedEntry] = useState<number | null>(null);

  // Load recorded snapshots from sessionStorage (survives crash/reload)
  const recorded = showHistory ? getRecordedSnapshots() : [];

  // Take initial snapshot on first render
  if (!lastSnapshotRef.current) {
    lastSnapshotRef.current = grabSnapshot();
  }

  useEffect(() => {
    if (!displaySnapshot && lastSnapshotRef.current) {
      setDisplaySnapshot(lastSnapshotRef.current);
    }
  }, [displaySnapshot]);

  const handleRefresh = () => {
    const next = grabSnapshot();
    const prev = lastSnapshotRef.current;
    if (prev) {
      const changes = diffSnapshots(prev, next);
      if (changes.length === 0) {
        setDiffText('(no changes)');
      } else {
        setDiffText(changes.join('\n'));
      }
    }
    lastSnapshotRef.current = next;
    setDisplaySnapshot(next);
  };

  const current = displaySnapshot ?? lastSnapshotRef.current ?? {};
  const fullText = JSON.stringify(
    { _meta: { renderCount: renderCount.current, capturedAt: new Date().toISOString() }, ...current },
    null,
    2,
  );

  return (
    <>
      <div className="flex items-center justify-between shrink-0">
        <span className="text-xs text-gray-400">
          Render #{renderCount.current} — snapshot at render time
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={handleRefresh}
            className="px-3 py-1.5 bg-yellow-600 hover:bg-yellow-700 text-white text-xs rounded"
          >
            Snapshot + Diff
          </button>
          <button
            onClick={() => setShowHistory(!showHistory)}
            className={`px-3 py-1.5 text-white text-xs rounded ${showHistory ? 'bg-purple-600 hover:bg-purple-700' : 'bg-purple-800 hover:bg-purple-700'}`}
          >
            {showHistory ? 'Hide' : 'Show'} Auto-Capture ({getRecordedSnapshots().length})
          </button>
          <button
            onClick={() => { clearRecordedSnapshots(); setShowHistory(false); }}
            className="px-3 py-1.5 bg-red-700 hover:bg-red-600 text-white text-xs rounded"
            title="Clear all recorded snapshots from sessionStorage"
          >
            Clear Snapshots
          </button>
          <button
            onClick={() => onCopy(fullText)}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded"
          >
            Copy
          </button>
        </div>
      </div>

      {/* Auto-captured history from before the crash */}
      {showHistory && (
        <div className="shrink-0 max-h-72 overflow-auto border border-purple-700/50 rounded bg-gray-950 p-2">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-purple-400">
              Auto-Captured Snapshots (recorded from DAG view, 100ms interval)
            </span>
            <button
              onClick={() => { clearRecordedSnapshots(); setShowHistory(false); }}
              className="px-2 py-0.5 bg-gray-700 hover:bg-gray-600 text-gray-300 text-[10px] rounded"
            >
              Clear
            </button>
          </div>
          {recorded.length === 0 ? (
            <p className="text-xs text-gray-500">No snapshots recorded yet. Navigate to the DAG view to start capturing.</p>
          ) : (
            <div className="space-y-1">
              {recorded.map((entry, i) => {
                const time = new Date(entry.ts).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
                const diffCount = entry.diff ? entry.diff.length : 0;
                const isExpanded = expandedEntry === i;
                return (
                  <div key={i} className="text-xs">
                    <button
                      onClick={() => setExpandedEntry(isExpanded ? null : i)}
                      className="w-full text-left flex items-center gap-2 px-2 py-1 rounded hover:bg-gray-800"
                    >
                      <span className="text-gray-500 font-mono">{time}</span>
                      <span className="text-gray-500">#{entry.seq}</span>
                      {entry.diff === null ? (
                        <span className="text-purple-400">(baseline)</span>
                      ) : diffCount === 0 ? (
                        <span className="text-gray-600">(no changes — skipped)</span>
                      ) : (
                        <span className="text-yellow-400">{diffCount} change{diffCount !== 1 ? 's' : ''}</span>
                      )}
                      <span className="ml-auto text-gray-600">{isExpanded ? '\u25B2' : '\u25BC'}</span>
                    </button>
                    {isExpanded && (
                      <pre className="ml-4 mt-1 mb-2 p-2 bg-gray-900 rounded text-[10px] font-mono whitespace-pre leading-relaxed max-h-40 overflow-auto">
                        {entry.diff === null
                          ? 'Initial baseline snapshot'
                          : entry.diff.map((line, j) => (
                              <div key={j} className={
                                line.startsWith('+') ? 'text-green-400' :
                                line.startsWith('-') ? 'text-red-400' :
                                line.startsWith('~') ? 'text-yellow-300' :
                                'text-gray-400'
                              }>{line}</div>
                            ))
                        }
                        <button
                          onClick={() => onCopy(JSON.stringify(entry.stores, null, 2))}
                          className="mt-2 px-2 py-0.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded"
                        >
                          Copy full snapshot
                        </button>
                      </pre>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Live diff */}
      {diffText !== null && (
        <div className="shrink-0 max-h-48 overflow-auto">
          <div className="text-xs font-semibold text-yellow-400 mb-1">Changes since last snapshot:</div>
          <pre className="bg-gray-950 border border-yellow-700/50 rounded p-2 text-xs font-mono whitespace-pre leading-relaxed">
            {diffText === '(no changes)'
              ? <span className="text-gray-500">{diffText}</span>
              : diffText.split('\n').map((line, i) => (
                  <div key={i} className={
                    line.startsWith('+') ? 'text-green-400' :
                    line.startsWith('-') ? 'text-red-400' :
                    line.startsWith('~') ? 'text-yellow-300' :
                    line.startsWith('    was:') ? 'text-red-400/70' :
                    line.startsWith('    now:') ? 'text-green-400/70' :
                    'text-gray-400'
                  }>{line}</div>
                ))
            }
          </pre>
        </div>
      )}
      <pre className="flex-1 overflow-auto bg-gray-950 border border-gray-700 rounded p-3 text-xs text-gray-300 font-mono whitespace-pre leading-relaxed">
        {fullText}
      </pre>
    </>
  );
}

function DebugLogSubTab({ onCopy }: { onCopy: (text: string) => void }) {
  const [entries, setEntries] = useState<DebugEntry[]>([]);

  useEffect(() => {
    setEntries(getDebugLog());
    const interval = setInterval(() => setEntries(getDebugLog()), 2000);
    return () => clearInterval(interval);
  }, []);

  const logText = entries.map((e) => `${e.ts} [${e.tag}] ${e.msg}`).join('\n');

  return (
    <>
      <div className="flex items-center justify-between shrink-0">
        <span className="text-xs text-gray-400">
          {entries.length} log entries (localStorage, survives reload)
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setEntries(getDebugLog())}
            className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded"
          >
            Refresh
          </button>
          <button
            onClick={() => onCopy(logText)}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded"
          >
            Copy
          </button>
          <button
            onClick={() => { clearDebugLog(); setEntries([]); }}
            className="px-3 py-1.5 bg-red-700 hover:bg-red-600 text-white text-xs rounded"
          >
            Clear
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-auto bg-gray-950 border border-gray-700 rounded p-3 font-mono text-xs">
        {entries.length === 0 ? (
          <p className="text-gray-500">No debug log entries yet</p>
        ) : (
          entries.slice().reverse().map((e, i) => (
            <div key={i} className="mb-1.5 pb-1.5 border-b border-gray-800/50">
              <span className="text-gray-500">{e.ts}</span>{' '}
              <span className="text-yellow-400">[{e.tag}]</span>
              <pre className="text-gray-300 whitespace-pre-wrap break-all mt-0.5 leading-relaxed">{e.msg}</pre>
            </div>
          ))
        )}
      </div>
    </>
  );
}

function ErrorsSubTab() {
  const errors = useErrorLogStore((s) => s.errors);
  const clear = useErrorLogStore((s) => s.clear);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  return (
    <>
      <div className="flex items-center justify-between shrink-0">
        <span className="text-xs text-gray-400">{errors.length} error{errors.length !== 1 ? 's' : ''} captured</span>
        {errors.length > 0 && (
          <button
            onClick={clear}
            className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded"
          >
            Clear
          </button>
        )}
      </div>
      {errors.length === 0 ? (
        <p className="text-sm text-gray-500">No errors since last refresh.</p>
      ) : (
        <div className="flex-1 overflow-auto space-y-2">
          {errors.map((entry) => (
            <div
              key={entry.id}
              className="bg-gray-800 rounded p-2 text-xs border border-gray-700"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <span className="text-gray-500">
                    {new Date(entry.timestamp).toLocaleTimeString()}
                  </span>
                  <span className="ml-2 px-1.5 py-0.5 bg-red-900/50 text-red-400 rounded text-[10px]">
                    {entry.source}
                  </span>
                </div>
                {entry.stack && (
                  <button
                    onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
                    className="text-gray-500 hover:text-gray-300 shrink-0"
                  >
                    {expandedId === entry.id ? '\u25B2' : '\u25BC'}
                  </button>
                )}
              </div>
              <p className="text-red-300 mt-1 break-words">{entry.message}</p>
              {expandedId === entry.id && entry.stack && (
                <pre className="mt-2 p-2 bg-gray-900 rounded text-gray-500 whitespace-pre-wrap break-words text-[10px] max-h-40 overflow-auto">
                  {entry.stack}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
