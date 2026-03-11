import { Handle, Position } from '@xyflow/react';
import type { DAGNodeData } from '../../types/dag';
import { useDAGStore } from '../../store/dagStore';

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

export function StageNode({ data }: { data: DAGNodeData }) {
  const setEditPromptStageKey = useDAGStore((s) => s.setEditPromptStageKey);
  const isInputDoc = data.artifact_type === 'project_doc';
  const isBranchingNode = data.artifact_type === 'component_map' || data.artifact_type === 'sub_component_map';
  const colorClass = isInputDoc
    ? 'bg-cyan-900 border-cyan-400'
    : isBranchingNode
    ? 'bg-indigo-900 border-indigo-400'
    : STATUS_COLORS[data.status] || STATUS_COLORS.pending;
  const statusLabel = isInputDoc ? 'Input' : isBranchingNode && data.status === 'pending' ? 'Branching' : (STATUS_LABELS[data.status] || data.status.replace('_', ' '));
  const pi = data.prompt_info;
  const isProcessing = data.is_active || ACTIVE_STATUSES.has(data.status);
  const spinnerColor = data.status === 'ai_reviewing' ? 'stage-spinner--purple' : 'stage-spinner--blue';

  const handleEditPrompt = (e: React.MouseEvent) => {
    e.stopPropagation(); // don't trigger node click (artifact select)
    if (pi) {
      setEditPromptStageKey(pi.stage_key);
    }
  };

  return (
    <div
      className={`px-4 py-3 rounded-lg border-2 shadow-lg min-w-[180px] ${colorClass} ${
        data.is_active ? 'ring-2 ring-blue-400 ring-offset-2 ring-offset-gray-900' : ''
      }`}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      <div className="font-semibold text-sm text-white flex items-center gap-1.5">
        {isProcessing && (
          <span className={`stage-spinner ${spinnerColor} shrink-0`} />
        )}
        {data.label}
      </div>
      {data.component_key && (
        <div className="text-xs text-gray-300 mt-0.5">{data.component_key}</div>
      )}
      <div className="text-xs mt-1 text-gray-300 flex items-center justify-between">
        <span>{statusLabel}</span>
        {data.has_artifact && data.version > 0 && (
          <span className="text-gray-500">v{data.version}</span>
        )}
      </div>
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
}
