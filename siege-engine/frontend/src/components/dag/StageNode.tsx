import { memo, useState } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { DAGNodeData } from '../../types/dag';
import { useDAGStore } from '../../store/dagStore';
import { useForceRestartStage, useCancelStage } from '../../hooks/mutations/usePipelineMutations';
import { RESTARTABLE_STATUSES } from '../../types/pipeline';

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-gray-700 border-gray-500',
  running: 'bg-blue-900 border-blue-400 animate-pulse',
  generating: 'bg-blue-900 border-blue-400 animate-pulse',
  ai_reviewing: 'bg-purple-900 border-purple-400 animate-pulse',
  awaiting_review: 'bg-yellow-900 border-yellow-400',
  approved: 'bg-green-900 border-green-400',
  rejected: 'bg-red-900 border-red-400',
  stale: 'bg-orange-900 border-orange-400',
  failed: 'bg-red-900 border-red-400',
};

const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  running: 'Running...',
  generating: 'Generating...',
  ai_reviewing: 'AI Reviewing...',
  awaiting_review: 'Awaiting Review',
  approved: 'Approved',
  rejected: 'Rejected',
  stale: 'Stale',
  failed: 'Failed',
};

function formatModelName(model: string): string {
  // "claude-sonnet-4-20250514" → "sonnet-4"
  const match = model.match(/claude-(\w+-\d+)/);
  return match ? match[1] : model;
}

const ACTIVE_STATUSES = new Set(['running', 'generating', 'ai_reviewing']);
const CANCELABLE_EXEC_STATUSES = new Set(['running', 'ai_review', 'pending']);

export const StageNode = memo(function StageNode({ data }: { data: DAGNodeData & { projectId?: string } }) {
  const projectId = data.projectId;
  const setEditPromptStageKey = useDAGStore((s) => s.setEditPromptStageKey);
  const forceRestartMutation = useForceRestartStage(projectId ?? '');
  const cancelStageMutation = useCancelStage(projectId ?? '');
  const [restarting, setRestarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const isInputDoc = data.artifact_type === 'project_doc';
  const isBranchingNode = data.artifact_type === 'component_map' || data.artifact_type === 'sub_component_map';
  const isPlaceholder = !data.has_artifact && data.is_active;
  const colorClass = isInputDoc
    ? 'bg-cyan-900 border-cyan-400'
    : isBranchingNode
    ? 'bg-indigo-900 border-indigo-400'
    : isPlaceholder
    ? 'bg-blue-900/60 border-blue-400 border-dashed animate-pulse'
    : STATUS_COLORS[data.status] || STATUS_COLORS.pending;
  const statusLabel = isPlaceholder ? 'Generating...' : isInputDoc ? 'Input' : isBranchingNode && data.status === 'pending' ? 'Branching' : (STATUS_LABELS[data.status] || (data.status ?? 'pending').replace('_', ' '));
  const pi = data.prompt_info;
  const isProcessing = data.is_active || ACTIVE_STATUSES.has(data.status);
  const spinnerColor = data.status === 'ai_reviewing' ? 'stage-spinner--purple' : 'stage-spinner--blue';

  const canRestart = !!(
    projectId
    && data.execution_id
    && data.execution_status
    && RESTARTABLE_STATUSES.has(data.execution_status)
  );

  const canCancel = !!(
    projectId
    && data.execution_id
    && data.execution_status
    && CANCELABLE_EXEC_STATUSES.has(data.execution_status)
  );

  const handleEditPrompt = (e: React.MouseEvent) => {
    e.stopPropagation(); // don't trigger node click (artifact select)
    if (pi) {
      setEditPromptStageKey(pi.stage_key);
    }
  };

  const handleRestart = async (e: React.MouseEvent) => {
    e.stopPropagation(); // don't trigger node click
    if (!projectId || !data.execution_id) return;
    setRestarting(true);
    try {
      await forceRestartMutation.mutateAsync(data.execution_id);
    } catch (err) {
      console.error('Force restart failed:', err);
    } finally {
      setRestarting(false);
    }
  };

  const handleCancel = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!projectId || !data.execution_id) return;
    setCancelling(true);
    try {
      await cancelStageMutation.mutateAsync(data.execution_id);
    } catch (err) {
      console.error('Cancel stage failed:', err);
    } finally {
      setCancelling(false);
    }
  };

  return (
    <div
      className={`px-4 py-3 rounded-lg border-2 shadow-lg w-[220px] overflow-hidden ${colorClass} ${
        data.is_active ? 'ring-2 ring-blue-400 ring-offset-2 ring-offset-gray-900' : ''
      }`}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      <div className="font-semibold text-sm text-white flex items-center gap-1.5 min-w-0">
        {isProcessing && (
          <span className={`stage-spinner ${spinnerColor} shrink-0`} />
        )}
        <span className="truncate">{data.label}</span>
      </div>
      {data.component_key && (
        <div className="text-xs text-gray-300 mt-0.5 truncate">{data.component_key}</div>
      )}
      <div className="text-xs mt-1 text-gray-300 flex items-center justify-between">
        <span>{statusLabel}</span>
        {data.has_artifact && data.version > 0 && (
          <span className="text-gray-500">v{data.version}</span>
        )}
      </div>
      {canCancel && (
        <button
          onClick={handleCancel}
          disabled={cancelling}
          className="mt-2 w-full px-2 py-1 bg-red-700 hover:bg-red-600 text-white text-xs rounded disabled:opacity-50"
        >
          {cancelling ? 'Cancelling...' : '✕ Cancel'}
        </button>
      )}
      {canRestart && !canCancel && (
        <button
          onClick={handleRestart}
          disabled={restarting}
          className="mt-2 w-full px-2 py-1 bg-orange-600 hover:bg-orange-500 text-white text-xs rounded disabled:opacity-50"
        >
          {restarting ? 'Restarting...' : '⟳ Restart'}
        </button>
      )}
      {pi && (
        <>
          <div className="border-t border-white/10 my-1.5" />
          <div className="text-xs text-gray-400 flex items-center justify-between">
            <span className="flex items-center gap-1">
              <span className="text-gray-500">⚙</span>
              {pi.model ? formatModelName(pi.model) : 'default model'}
              {pi.has_custom_config && (
                <span className="text-blue-400" title="Custom prompt config">✎</span>
              )}
            </span>
            <button
              onClick={handleEditPrompt}
              className="text-gray-500 hover:text-blue-400 transition-colors"
              title="Edit prompt config"
            >
              Edit
            </button>
          </div>
        </>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-gray-400" />
    </div>
  );
});
