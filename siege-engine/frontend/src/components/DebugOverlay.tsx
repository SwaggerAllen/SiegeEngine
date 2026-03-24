import { useState, useEffect } from 'react';
import { getDebugLog, clearDebugLog, type DebugEntry } from '../lib/debugLog';

/**
 * Floating debug overlay that reads from localStorage.
 * Shows a small "DBG" button in the bottom-left corner.
 * Tap to expand, see recent logs, and clear them.
 */
export function DebugOverlay() {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<DebugEntry[]>([]);

  // Refresh entries when opened, and poll every 2s while open
  useEffect(() => {
    if (!open) return;
    setEntries(getDebugLog());
    const interval = setInterval(() => setEntries(getDebugLog()), 2000);
    return () => clearInterval(interval);
  }, [open]);

  const handleClear = () => {
    clearDebugLog();
    setEntries([]);
  };

  const handleCopy = async () => {
    const text = entries.map((e) => `${e.ts} [${e.tag}] ${e.msg}`).join('\n');
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Fallback for mobile browsers that block clipboard API
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-2 left-2 z-[9999] px-2 py-1 bg-yellow-600 text-black text-xs font-bold rounded shadow-lg opacity-70"
      >
        DBG
      </button>
    );
  }

  return (
    <div className="fixed inset-x-2 bottom-2 top-1/3 z-[9999] bg-black/95 border border-yellow-600 rounded-lg shadow-2xl flex flex-col text-xs">
      <div className="flex items-center justify-between px-3 py-2 border-b border-yellow-600/50 shrink-0">
        <span className="text-yellow-400 font-bold">Debug Log ({entries.length})</span>
        <div className="flex gap-2">
          <button
            onClick={handleCopy}
            className="px-2 py-0.5 bg-blue-700 text-white rounded text-xs"
          >
            Copy
          </button>
          <button
            onClick={handleClear}
            className="px-2 py-0.5 bg-red-700 text-white rounded text-xs"
          >
            Clear
          </button>
          <button
            onClick={() => setOpen(false)}
            className="px-2 py-0.5 bg-gray-700 text-white rounded text-xs"
          >
            Close
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-auto p-2 font-mono">
        {entries.length === 0 ? (
          <p className="text-gray-500">No debug entries yet</p>
        ) : (
          entries.slice().reverse().map((e, i) => (
            <div key={i} className="mb-1.5 border-b border-gray-800 pb-1.5">
              <span className="text-gray-500">{e.ts}</span>{' '}
              <span className="text-yellow-400">[{e.tag}]</span>
              <pre className="text-gray-300 whitespace-pre-wrap break-all mt-0.5">{e.msg}</pre>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
