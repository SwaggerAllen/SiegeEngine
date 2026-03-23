/**
 * Auto-captures Zustand store snapshots to sessionStorage on an interval.
 * Survives page reloads so the debug view can show what happened before a crash.
 */
import { usePipelineStore } from '../store/pipelineStore';
import { useDAGStore } from '../store/dagStore';
import { useProjectStore } from '../store/projectStore';
import { useAuthStore } from '../store/authStore';
import { useErrorLogStore } from '../store/errorLogStore';

const STORAGE_KEY = 'siege_debug_snapshots';
const MAX_ENTRIES = 20;

interface SnapshotEntry {
  ts: string;
  seq: number;
  stores: Record<string, unknown>;
  diff: string[] | null; // null for the first entry
}

/** Strip functions, truncate large values for storage */
function sanitize(obj: unknown, depth = 0): unknown {
  if (depth > 4) return '(max depth)';
  if (obj === null || obj === undefined) return obj;
  if (typeof obj === 'function') return undefined; // strip entirely to save space
  if (typeof obj === 'string') {
    return obj.length > 120 ? obj.slice(0, 120) + '...' : obj;
  }
  if (typeof obj !== 'object') return obj;
  if (Array.isArray(obj)) {
    if (obj.length > 10) {
      return [`(${obj.length} items)`];
    }
    return obj.map((v) => sanitize(v, depth + 1)).filter((v) => v !== undefined);
  }
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    const s = sanitize(v, depth + 1);
    if (s !== undefined) out[k] = s;
  }
  return out;
}

function grabStores(): Record<string, unknown> {
  return {
    pipeline: sanitize(usePipelineStore.getState()),
    dag: sanitize(useDAGStore.getState()),
    project: sanitize(useProjectStore.getState()),
    auth: sanitize(useAuthStore.getState()),
    errors: sanitize(useErrorLogStore.getState()),
  };
}

function diffObjects(
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
    if (a === undefined && b !== undefined) {
      lines.push(`+ ${path}`);
    } else if (a !== undefined && b === undefined) {
      lines.push(`- ${path}`);
    } else if (
      typeof a === 'object' && a !== null &&
      typeof b === 'object' && b !== null &&
      !Array.isArray(a) && !Array.isArray(b)
    ) {
      lines.push(...diffObjects(a as Record<string, unknown>, b as Record<string, unknown>, path));
    } else {
      const aStr = JSON.stringify(a);
      const bStr = JSON.stringify(b);
      if (aStr !== bStr) {
        lines.push(`~ ${path}`);
      }
    }
  }
  return lines;
}

let seq = 0;
let lastStores: Record<string, unknown> | null = null;
let intervalId: ReturnType<typeof setInterval> | null = null;
let activeCount = 0;

function capture() {
  const stores = grabStores();
  const diff = lastStores ? diffObjects(lastStores, stores) : null;

  // Skip if nothing changed (don't waste storage on identical frames)
  if (diff && diff.length === 0) return;

  seq++;
  const entry: SnapshotEntry = {
    ts: new Date().toISOString(),
    seq,
    stores,
    diff,
  };

  lastStores = stores;

  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    const existing: SnapshotEntry[] = raw ? JSON.parse(raw) : [];
    existing.push(entry);
    // Keep only last MAX_ENTRIES
    while (existing.length > MAX_ENTRIES) existing.shift();
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(existing));
  } catch {
    // sessionStorage full or unavailable — drop oldest half
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      const existing: SnapshotEntry[] = raw ? JSON.parse(raw) : [];
      const trimmed = existing.slice(Math.floor(existing.length / 2));
      trimmed.push(entry);
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
    } catch {
      // give up silently
    }
  }
}

/** Start auto-capturing every 500ms. Call the returned function to stop. */
export function startRecording(): () => void {
  activeCount++;
  if (activeCount === 1) {
    // Take an immediate baseline
    capture();
    intervalId = setInterval(capture, 100);
  }
  return () => {
    activeCount--;
    if (activeCount <= 0) {
      activeCount = 0;
      if (intervalId !== null) {
        clearInterval(intervalId);
        intervalId = null;
      }
    }
  };
}

/** Read all captured snapshots from sessionStorage */
export function getRecordedSnapshots(): SnapshotEntry[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

/** Clear recorded snapshots */
export function clearRecordedSnapshots(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}
