import { useRef } from 'react';
import { usePipelineStore } from '../../store/pipelineStore';
import { useDAGStore } from '../../store/dagStore';
import { useProjectStore } from '../../store/projectStore';
import { useAuthStore } from '../../store/authStore';
import { useErrorLogStore } from '../../store/errorLogStore';

/**
 * Shows a snapshot of ALL Zustand store state as it was at render time.
 * No polling, no throttling — just reads current values during render.
 * A render counter tracks how often the parent re-renders.
 */
export function ZustandStatePanel() {
  const renderCount = useRef(0);
  renderCount.current += 1;

  // Read entire store states (these are the values at render time)
  const pipelineState = usePipelineStore.getState();
  const dagState = useDAGStore.getState();
  const projectState = useProjectStore.getState();
  const authState = useAuthStore.getState();
  const errorState = useErrorLogStore.getState();

  const snapshot = {
    _meta: {
      renderCount: renderCount.current,
      capturedAt: new Date().toISOString(),
    },
    pipeline: sanitize(pipelineState),
    dag: sanitize(dagState),
    project: sanitize(projectState),
    auth: sanitize(authState),
    errors: sanitize(errorState),
  };

  const text = JSON.stringify(snapshot, null, 2);

  return (
    <div className="h-full flex flex-col p-4 gap-3">
      <div className="flex items-center justify-between shrink-0">
        <h2 className="text-lg font-bold text-white">
          Zustand State (render #{renderCount.current})
        </h2>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">
            Snapshot taken at render time — no live updates
          </span>
          <button
            onClick={() => navigator.clipboard.writeText(text)}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded"
          >
            Copy
          </button>
        </div>
      </div>
      <pre className="flex-1 overflow-auto bg-gray-950 border border-gray-700 rounded p-3 text-xs text-gray-300 font-mono whitespace-pre leading-relaxed">
        {text}
      </pre>
    </div>
  );
}

/** Strip functions from state for display, truncate large strings/arrays */
function sanitize(obj: unknown, depth = 0): unknown {
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
        ...obj.slice(0, 10).map((v) => sanitize(v, depth + 1)),
        `...(${obj.length} items total)`,
      ];
    }
    return obj.map((v) => sanitize(v, depth + 1));
  }
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    out[k] = sanitize(v, depth + 1);
  }
  return out;
}
