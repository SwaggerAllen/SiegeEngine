import { Handle, Position } from '@xyflow/react';
import type { DAGNodeData } from '../../types/dag';

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-gray-700 border-gray-500',
  generating: 'bg-blue-900 border-blue-400 animate-pulse',
  ai_reviewing: 'bg-purple-900 border-purple-400 animate-pulse',
  awaiting_review: 'bg-yellow-900 border-yellow-400',
  approved: 'bg-green-900 border-green-400',
  rejected: 'bg-red-900 border-red-400',
  stale: 'bg-orange-900 border-orange-400',
};

export function StageNode({ data }: { data: DAGNodeData }) {
  const colorClass = STATUS_COLORS[data.status] || STATUS_COLORS.pending;

  return (
    <div className={`px-4 py-3 rounded-lg border-2 shadow-lg min-w-[180px] ${colorClass}`}>
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      <div className="font-semibold text-sm text-white">{data.label}</div>
      {data.component_key && (
        <div className="text-xs text-gray-300 mt-0.5">{data.component_key}</div>
      )}
      <div className="text-xs mt-1 capitalize text-gray-300">{data.status.replace('_', ' ')}</div>
      <Handle type="source" position={Position.Bottom} className="!bg-gray-400" />
    </div>
  );
}
