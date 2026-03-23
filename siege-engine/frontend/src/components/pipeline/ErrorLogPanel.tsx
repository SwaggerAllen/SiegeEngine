import { useState } from 'react';
import { useErrorLogStore } from '../../store/errorLogStore';

export function ErrorLogPanel() {
  const errors = useErrorLogStore((s) => s.errors);
  const clear = useErrorLogStore((s) => s.clear);
  const [copied, setCopied] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const formatForCopy = () => {
    if (errors.length === 0) return 'No errors captured.';
    return errors
      .map((e) => {
        let text = `[${e.timestamp}] (${e.source}) ${e.message}`;
        if (e.stack) text += `\n${e.stack}`;
        return text;
      })
      .join('\n\n');
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(formatForCopy());
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for mobile Safari
      const textarea = document.createElement('textarea');
      textarea.value = formatForCopy();
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-300">
          Error Log ({errors.length})
        </h3>
        <div className="flex gap-2">
          <button
            onClick={handleCopy}
            className="px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white text-xs rounded"
          >
            {copied ? 'Copied!' : 'Copy All'}
          </button>
          {errors.length > 0 && (
            <button
              onClick={clear}
              className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {errors.length === 0 ? (
        <p className="text-sm text-gray-500">No errors since last refresh.</p>
      ) : (
        <div className="space-y-2 max-h-[calc(100vh-200px)] overflow-auto">
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
                    onClick={() =>
                      setExpandedId(expandedId === entry.id ? null : entry.id)
                    }
                    className="text-gray-500 hover:text-gray-300 shrink-0"
                  >
                    {expandedId === entry.id ? '▲' : '▼'}
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
    </div>
  );
}
