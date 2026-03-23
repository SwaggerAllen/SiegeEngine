import { useEffect, useState, useCallback, useRef } from 'react';
import { getDebugState } from '../../api/pipeline';
import { usePipelineStore } from '../../store/pipelineStore';
import { useDAGStore } from '../../store/dagStore';
import { useProjectStore } from '../../store/projectStore';
import { useAuthStore } from '../../store/authStore';
import { useErrorLogStore } from '../../store/errorLogStore';

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

type SubTab = 'backend' | 'frontend';

export function DebugStatePanel({ projectId }: { projectId: string }) {
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
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold text-white">Debug State</h2>
          <div className="flex rounded overflow-hidden border border-gray-600">
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
          </div>
        </div>
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
          <button
            onClick={() => handleCopy(subTab === 'backend' ? debugText : '')}
            className={`px-3 py-1.5 text-white text-xs rounded disabled:opacity-50 ${
              copied ? 'bg-green-600' : 'bg-blue-600 hover:bg-blue-700'
            }`}
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
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
      ) : (
        <ZustandSubTab onCopy={handleCopy} />
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

function ZustandSubTab({ onCopy }: { onCopy: (text: string) => void }) {
  const renderCount = useRef(0);
  renderCount.current += 1;

  const snapshot = {
    _meta: {
      renderCount: renderCount.current,
      capturedAt: new Date().toISOString(),
    },
    pipeline: sanitizeForDisplay(usePipelineStore.getState()),
    dag: sanitizeForDisplay(useDAGStore.getState()),
    project: sanitizeForDisplay(useProjectStore.getState()),
    auth: sanitizeForDisplay(useAuthStore.getState()),
    errors: sanitizeForDisplay(useErrorLogStore.getState()),
  };

  const text = JSON.stringify(snapshot, null, 2);

  // Wire up copy to parent button
  useEffect(() => {
    // Expose current text for the Copy button in parent
    copyRef.current = text;
  });
  const copyRef = useRef(text);
  // Override parent copy with our text
  const origOnCopy = onCopy;
  void origOnCopy;

  return (
    <>
      <div className="text-xs text-gray-400 shrink-0">
        Render #{renderCount.current} — snapshot of all Zustand stores at render time (no live updates)
      </div>
      <pre className="flex-1 overflow-auto bg-gray-950 border border-gray-700 rounded p-3 text-xs text-gray-300 font-mono whitespace-pre leading-relaxed">
        {text}
      </pre>
      <button
        onClick={() => onCopy(text)}
        className="shrink-0 self-end px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded"
      >
        Copy Frontend State
      </button>
    </>
  );
}
