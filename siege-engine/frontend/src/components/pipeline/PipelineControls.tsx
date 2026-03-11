import { useState, useRef, useEffect } from 'react';
import { usePipelineStore } from '../../store/pipelineStore';
import type { PipelineStartOptions } from '../../types/pipeline';

const STOP_POINT_OPTIONS = [
  { value: 'after_all', label: 'Only when needed' },
  { value: 'before_code', label: 'Before code generation' },
  { value: 'at_fan_out', label: 'At fan-out points' },
  { value: 'after_triplets', label: 'After each req\u2192arch\u2192plan group' },
];

export function PipelineControls({ projectId }: { projectId: string }) {
  const { isRunning, isPaused, currentRunNumber, startPipeline, cancelPipeline } =
    usePipelineStore();
  const [showConfig, setShowConfig] = useState(false);
  const [humanReview, setHumanReview] = useState(true);
  const [aiLoops, setAiLoops] = useState(1);
  const [stopPoint, setStopPoint] = useState('after_all');
  const panelRef = useRef<HTMLDivElement>(null);

  // Close popover on outside click
  useEffect(() => {
    if (!showConfig) return;
    const handleClick = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setShowConfig(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showConfig]);

  const handleStart = async () => {
    const options: PipelineStartOptions = {
      human_review: humanReview,
      ai_loops: aiLoops,
      stop_point: stopPoint,
    };
    setShowConfig(false);
    await startPipeline(projectId, options);
  };

  return (
    <div className="flex items-center gap-2 relative">
      {!isRunning ? (
        <div ref={panelRef}>
          <button
            onClick={() => setShowConfig(!showConfig)}
            className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-xs md:text-sm rounded min-h-[44px] md:min-h-0 flex items-center gap-1"
          >
            <span>Start Run</span>
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {showConfig && (
            <div className="absolute top-full mt-1 right-0 z-50 w-72 bg-gray-800 border border-gray-600 rounded-lg shadow-xl p-4 space-y-3">
              <h3 className="text-sm font-semibold text-white">Run Configuration</h3>

              {/* Human Review Toggle */}
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={humanReview}
                  onChange={(e) => setHumanReview(e.target.checked)}
                  className="w-4 h-4 rounded border-gray-500 bg-gray-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-0"
                />
                <span className="text-sm text-gray-300">Include human review</span>
              </label>

              {/* AI Loops */}
              <div>
                <label className="block text-sm text-gray-300 mb-1">
                  AI self-improvement loops
                </label>
                <input
                  type="number"
                  min={0}
                  max={10}
                  value={aiLoops}
                  onChange={(e) => setAiLoops(Math.max(0, Math.min(10, parseInt(e.target.value) || 0)))}
                  className="w-20 px-2 py-1 bg-gray-700 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                />
              </div>

              {/* Stop Point */}
              <div>
                <label className="block text-sm text-gray-300 mb-1">Pause at</label>
                <select
                  value={stopPoint}
                  onChange={(e) => setStopPoint(e.target.value)}
                  className="w-full px-2 py-1.5 bg-gray-700 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                >
                  {STOP_POINT_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Start Button */}
              <button
                onClick={handleStart}
                className="w-full py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded font-medium"
              >
                Start
              </button>
            </div>
          )}
        </div>
      ) : (
        <>
          <button
            onClick={() => cancelPipeline(projectId)}
            className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-xs md:text-sm rounded min-h-[44px] md:min-h-0"
          >
            Cancel
          </button>
          {currentRunNumber && (
            <span className="text-xs bg-gray-700 text-gray-300 px-2 py-1 rounded">
              Run #{currentRunNumber}
            </span>
          )}
        </>
      )}
      {isPaused && (
        <span className="text-yellow-400 text-sm">Paused for review</span>
      )}
      {isRunning && !isPaused && (
        <span className="text-blue-400 text-sm animate-pulse">Running...</span>
      )}
    </div>
  );
}
