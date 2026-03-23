import { useState, useRef, useEffect } from 'react';
import { usePipelineStore } from '../../store/pipelineStore';

export function PipelineControls({ projectId, hasGitHub }: { projectId: string; hasGitHub?: boolean }) {
  const isRunning = usePipelineStore((s) => s.isRunning);
  const isPaused = usePipelineStore((s) => s.isPaused);
  const currentRunNumber = usePipelineStore((s) => s.currentRunNumber);
  const runs = usePipelineStore((s) => s.runs);
  const blockingPR = usePipelineStore((s) => s.blockingPR);
  const cancelPipeline = usePipelineStore((s) => s.cancelPipeline);
  const resetAll = usePipelineStore((s) => s.resetAll);
  const checkBlockingPR = usePipelineStore((s) => s.checkBlockingPR);
  const dismissBlockingPR = usePipelineStore((s) => s.dismissBlockingPR);
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [checkingPR, setCheckingPR] = useState(false);
  const [prCleared, setPrCleared] = useState(false);
  const cancelRef = useRef<HTMLDivElement>(null);
  const resetConfirmRef = useRef<HTMLDivElement>(null);

  const hasCompletedRun = runs.some(
    (r) => r.status === 'completed' || r.status === 'paused' || r.status === 'cancelled' || r.status === 'failed'
  );

  // Close popover on outside click
  useEffect(() => {
    if (!showCancelDialog && !showResetConfirm) return;
    const handleClick = (e: MouseEvent) => {
      if (showCancelDialog && cancelRef.current && !cancelRef.current.contains(e.target as Node)) {
        setShowCancelDialog(false);
      }
      if (showResetConfirm && resetConfirmRef.current && !resetConfirmRef.current.contains(e.target as Node)) {
        setShowResetConfirm(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showCancelDialog, showResetConfirm]);

  const [cancelError, setCancelError] = useState<string | null>(null);

  const handleCancel = async (openPR: boolean) => {
    setShowCancelDialog(false);
    setCancelError(null);
    try {
      await cancelPipeline(projectId, openPR ? { open_pr: true } : undefined);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to create PR';
      setCancelError(message);
    }
  };

  const handleResetAll = async () => {
    setShowResetConfirm(false);
    setShowCancelDialog(false);
    setCancelError(null);
    try {
      await resetAll(projectId);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Reset failed';
      setCancelError(message);
    }
  };

  const handleCheckPR = async () => {
    setCheckingPR(true);
    try {
      const stillBlocking = await checkBlockingPR(projectId);
      if (!stillBlocking) {
        setPrCleared(true);
      }
    } finally {
      setCheckingPR(false);
    }
  };

  // Auto-dismiss the "PR resolved" message
  useEffect(() => {
    if (!prCleared) return;
    const timer = setTimeout(() => setPrCleared(false), 4000);
    return () => clearTimeout(timer);
  }, [prCleared]);

  // Blocking PR banner
  if (blockingPR && !isRunning) {
    return (
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-yellow-900/40 border border-yellow-600/50 rounded text-xs">
          <svg className="w-3.5 h-3.5 text-yellow-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span className="text-yellow-300">
            Blocked by{' '}
            <a href={blockingPR.url} target="_blank" rel="noreferrer" className="underline hover:text-yellow-100">
              PR #{blockingPR.number}
            </a>
          </span>
          <button
            onClick={handleCheckPR}
            disabled={checkingPR}
            className="px-2 py-0.5 bg-yellow-700 hover:bg-yellow-600 text-white rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
          >
            {checkingPR ? 'Checking...' : 'Check PR'}
          </button>
          <button
            onClick={() => dismissBlockingPR(projectId)}
            className="px-2 py-0.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded min-h-[44px] md:min-h-0"
          >
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 relative">
      {!isRunning ? (
        <div className="flex items-center gap-1.5">
          {hasCompletedRun && (
            <div ref={resetConfirmRef} className="relative">
              <button
                onClick={() => setShowResetConfirm(true)}
                className="px-3 py-1.5 bg-orange-600 hover:bg-orange-700 text-white text-xs md:text-sm rounded min-h-[44px] md:min-h-0"
                title="Reset all pipeline state to a clean slate"
              >
                Reset All
              </button>
              {showResetConfirm && (
                <div className="absolute top-full mt-1 right-0 z-50 w-64 bg-gray-800 border border-gray-600 rounded-lg shadow-xl p-4 space-y-3">
                  <h3 className="text-sm font-semibold text-white">Reset Pipeline</h3>
                  <p className="text-xs text-gray-400">
                    Stops all activity and puts every document with content into
                    &ldquo;Awaiting Review&rdquo;. You can then review each one and start a
                    fresh run.
                  </p>
                  <button
                    onClick={handleResetAll}
                    className="w-full py-1.5 bg-orange-600 hover:bg-orange-700 text-white text-sm rounded"
                  >
                    Confirm Reset
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div ref={cancelRef} className="relative flex items-center gap-2">
          <button
            onClick={() => setShowCancelDialog(true)}
            className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-xs md:text-sm rounded min-h-[44px] md:min-h-0"
          >
            Cancel
          </button>
          {currentRunNumber && (
            <span className="text-xs bg-gray-700 text-gray-300 px-2 py-1 rounded">
              Run #{currentRunNumber}
            </span>
          )}

          {showCancelDialog && (
            <div className="absolute top-full mt-1 right-0 z-50 w-64 bg-gray-800 border border-gray-600 rounded-lg shadow-xl p-4 space-y-3">
              <h3 className="text-sm font-semibold text-white">Cancel Run</h3>
              <p className="text-xs text-gray-400">
                All in-progress nodes will be marked as failed.
              </p>
              <div className="flex flex-col gap-2">
                <button
                  onClick={() => handleCancel(false)}
                  className="w-full py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm rounded"
                >
                  Cancel Run
                </button>
                {hasGitHub && (
                  <button
                    onClick={() => handleCancel(true)}
                    className="w-full py-1.5 bg-purple-600 hover:bg-purple-700 text-white text-sm rounded"
                  >
                    Cancel &amp; Open PR
                  </button>
                )}
                <div className="border-t border-gray-600 pt-2 mt-1">
                  <button
                    onClick={handleResetAll}
                    className="w-full py-1.5 bg-orange-600 hover:bg-orange-700 text-white text-sm rounded"
                  >
                    Reset All (Clean Slate)
                  </button>
                  <p className="text-[10px] text-gray-500 mt-1">
                    Stops everything and puts all documents into review.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
      {prCleared && (
        <span className="text-green-400 text-xs">PR resolved — runs unblocked</span>
      )}
      {cancelError && (
        <span className="text-red-400 text-xs max-w-xs truncate" title={cancelError}>{cancelError}</span>
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
