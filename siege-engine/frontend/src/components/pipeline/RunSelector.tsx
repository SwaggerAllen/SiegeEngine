import { useEffect, useRef, useState } from 'react';
import { usePipelineStore } from '../../store/pipelineStore';
import type { PipelineRun } from '../../types/pipeline';
import { formatDateShort } from '../../utils/dateFormat';

export function RunSelector({ projectId }: { projectId: string }) {
  const runs = usePipelineStore((s) => s.runs);
  const fetchRuns = usePipelineStore((s) => s.fetchRuns);
  const selectedRunNumber = usePipelineStore((s) => s.selectedRunNumber);
  const isViewingHistory = usePipelineStore((s) => s.isViewingHistory);
  const selectRun = usePipelineStore((s) => s.selectRun);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchRuns(projectId);
  }, [projectId, fetchRuns]);

  // Close dropdown on outside click
  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  if (runs.length === 0) return null;

  const statusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'text-green-400';
      case 'running': return 'text-blue-400';
      case 'paused': return 'text-yellow-400';
      case 'failed': return 'text-red-400';
      case 'cancelled': return 'text-gray-400';
      default: return 'text-gray-400';
    }
  };

  const label = isViewingHistory && selectedRunNumber
    ? `Run #${selectedRunNumber}`
    : 'Current';

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded flex items-center gap-1 min-h-[44px] md:min-h-0"
      >
        <span>{label}</span>
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute top-full mt-1 right-0 z-50 w-56 bg-gray-800 border border-gray-600 rounded-lg shadow-xl overflow-hidden">
          {/* Current / live option */}
          <button
            onClick={() => { selectRun(projectId, null); setOpen(false); }}
            className={`w-full px-3 py-2 text-left text-sm hover:bg-gray-700 flex items-center justify-between ${
              !isViewingHistory ? 'bg-gray-700 text-white' : 'text-gray-300'
            }`}
          >
            <span>Current (live)</span>
            {!isViewingHistory && (
              <span className="text-blue-400 text-xs">●</span>
            )}
          </button>

          <div className="border-t border-gray-700" />

          {/* Historical runs */}
          <div className="max-h-48 overflow-y-auto">
            {runs.map((run: PipelineRun) => (
              <button
                key={run.id}
                onClick={() => { selectRun(projectId, run.run_number); setOpen(false); }}
                disabled={!run.git_commit_sha}
                className={`w-full px-3 py-2 text-left text-sm hover:bg-gray-700 flex items-center justify-between disabled:opacity-40 disabled:cursor-not-allowed ${
                  isViewingHistory && selectedRunNumber === run.run_number
                    ? 'bg-gray-700 text-white'
                    : 'text-gray-300'
                }`}
              >
                <div className="flex flex-col">
                  <span>Run #{run.run_number}</span>
                  {run.completed_at && (
                    <span className="text-xs text-gray-500">
                      {formatDateShort(run.completed_at)}
                    </span>
                  )}
                </div>
                <span className={`text-xs ${statusColor(run.status)}`}>
                  {run.status}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
