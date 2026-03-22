import { useEffect, useRef, useState } from 'react';
import { usePipelineStore } from '../../store/pipelineStore';

const LEVEL_COLORS: Record<string, string> = {
  error: 'text-red-400',
  warning: 'text-yellow-400',
  info: 'text-gray-300',
  debug: 'text-gray-500',
};

export function LogPanel() {
  const logEntries = usePipelineStore((s) => s.logEntries);
  const clearLogs = usePipelineStore((s) => s.clearLogs);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logEntries.length, autoScroll]);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    // Auto-scroll when user is near the bottom
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAutoScroll(atBottom);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-700 bg-gray-800">
        <span className="text-xs font-medium text-gray-400">
          Backend Logs ({logEntries.length})
        </span>
        <button
          onClick={clearLogs}
          className="text-xs text-gray-500 hover:text-gray-300"
        >
          Clear
        </button>
      </div>
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto font-mono text-xs p-2 bg-gray-900 space-y-0"
      >
        {logEntries.length === 0 && (
          <span className="text-gray-600">No logs yet. Logs appear when a stage runs.</span>
        )}
        {logEntries.map((entry, i) => {
          const time = entry.timestamp.split('T')[1]?.slice(0, 12) ?? '';
          const color = LEVEL_COLORS[entry.level] ?? 'text-gray-300';
          return (
            <div key={i} className={`${color} leading-5 whitespace-pre-wrap break-all`}>
              <span className="text-gray-600">{time}</span>{' '}
              <span className="uppercase font-semibold">{entry.level.slice(0, 4)}</span>{' '}
              {entry.message}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
