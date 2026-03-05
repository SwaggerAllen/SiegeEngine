import { usePipelineStore } from '../../store/pipelineStore';

export function PipelineControls({ projectId }: { projectId: string }) {
  const { isRunning, isPaused, startPipeline, cancelPipeline } =
    usePipelineStore();

  return (
    <div className="flex flex-wrap items-center gap-2">
      {!isRunning ? (
        <>
          <button
            onClick={() => startPipeline(projectId, 'gated')}
            className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-xs md:text-sm rounded min-h-[44px] md:min-h-0"
          >
            Start (Gated)
          </button>
          <button
            onClick={() => startPipeline(projectId, 'async')}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs md:text-sm rounded min-h-[44px] md:min-h-0"
          >
            Start (Async)
          </button>
        </>
      ) : (
        <button
          onClick={() => cancelPipeline(projectId)}
          className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-xs md:text-sm rounded min-h-[44px] md:min-h-0"
        >
          Cancel
        </button>
      )}
      {isPaused && (
        <span className="text-yellow-400 text-sm">Pipeline paused for review</span>
      )}
      {isRunning && !isPaused && (
        <span className="text-blue-400 text-sm animate-pulse">Running...</span>
      )}
    </div>
  );
}
