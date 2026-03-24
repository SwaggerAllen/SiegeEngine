/**
 * localStorage-based debug logger for mobile debugging.
 * Stores recent log entries in localStorage and provides
 * a way to read them from a floating overlay.
 */

const STORAGE_KEY = 'siege_debug_log';
const MAX_ENTRIES = 50;

export interface DebugEntry {
  ts: string;
  tag: string;
  msg: string;
}

function now(): string {
  return new Date().toISOString().slice(11, 23); // HH:mm:ss.SSS
}

function readLog(): DebugEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function writeLog(entries: DebugEntry[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(-MAX_ENTRIES)));
  } catch {
    // localStorage full or unavailable — ignore
  }
}

export function debugLog(tag: string, msg: string) {
  const entries = readLog();
  entries.push({ ts: now(), tag, msg });
  writeLog(entries);
  console.debug(`[${tag}]`, msg);
}

export function debugError(tag: string, error: unknown) {
  const msg = error instanceof Error
    ? `${error.message}\n${error.stack?.split('\n').slice(0, 3).join('\n') ?? ''}`
    : String(error);
  debugLog(tag, msg);
}

export function getDebugLog(): DebugEntry[] {
  return readLog();
}

export function clearDebugLog() {
  localStorage.removeItem(STORAGE_KEY);
}
