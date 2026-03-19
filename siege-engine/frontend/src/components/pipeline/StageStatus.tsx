import { useState } from 'react';
import type { StageExecution } from '../../types/pipeline';
import { RESTARTABLE_STATUSES } from '../../types/pipeline';
import { usePipelineStore } from '../../store/pipelineStore';

const STATUS_BADGES: Record<string, { bg: string; text: string }> = {
  pending: { bg: 'bg-gray-600', text: 'Pending' },
  running: { bg: 'bg-blue-600 animate-pulse', text: 'Running' },
  ai_review: { bg: 'bg-purple-600 animate-pulse', text: 'AI Review' },
  awaiting_review: { bg: 'bg-yellow-600', text: 'Awaiting Review' },
  approved: { bg: 'bg-green-600', text: 'Approved' },
  rejected: { bg: 'bg-red-600', text: 'Rejected' },
  skipped: { bg: 'bg-gray-500', text: 'Skipped' },
  failed: { bg: 'bg-red-700', text: 'Failed' },
};

function formatTimestamp(ts: string): string {
  const d = new Date(ts);
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', second: '2-digit' });
}

function formatDuration(startedAt: string, completedAt: string): string {
  const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime();
  if (ms < 0) return '';
  const totalSecs = Math.floor(ms / 1000);
  if (totalSecs < 60) return `${totalSecs}s`;
  const mins = Math.floor(totalSecs / 60);
  const secs = totalSecs % 60;
  if (mins < 60) return `${mins}m ${secs}s`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;
}

function ExecutionRow({ exec, projectId }: { exec: StageExecution; projectId?: string }) {
  const [expanded, setExpanded] = useState(false);
  const [actionInProgress, setActionInProgress] = useState(false);
  const badge = STATUS_BADGES[exec.status] || STATUS_BADGES.pending;
  const { forceRestartStage } = usePipelineStore();

  const handleForceRestart = async () => {
    if (!projectId) return;
    setActionInProgress(true);
    try {
      await forceRestartStage(projectId, exec.id);
    } catch (err) {
      console.error('Force restart failed:', err);
    } finally {
      setActionInProgress(false);
    }
  };

  const canForceRestart = projectId && RESTARTABLE_STATUSES.has(exec.status);

  return (
    <div key={exec.id} className="text-xs">
      <div className="flex items-center gap-2">
        <span className={`px-1.5 py-0.5 rounded text-white shrink-0 ${badge.bg}`}>
          {badge.text}
        </span>
        {exec.component_key && (
          <span className="text-gray-400 shrink-0">{exec.component_key}</span>
        )}
        {exec.error_message && (
          <>
            <span
              className={`text-red-400 ${expanded ? '' : 'truncate'} min-w-0`}
            >
              {expanded ? '' : exec.error_message}
            </span>
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-gray-500 hover:text-gray-300 shrink-0 ml-auto"
            >
              {expanded ? '▲' : '▼'}
            </button>
          </>
        )}
        {canForceRestart && (
          <button
            onClick={handleForceRestart}
            disabled={actionInProgress}
            className="ml-auto px-1.5 py-0.5 rounded text-white bg-orange-600 hover:bg-orange-500 disabled:opacity-50 shrink-0"
            title="Force restart this stage"
          >
            {actionInProgress ? '...' : '⟳ Restart'}
          </button>
        )}
      </div>
      {exec.started_at && (
        <div className="text-gray-500 mt-0.5 pl-0.5">
          {formatTimestamp(exec.started_at)}
          {exec.completed_at
            ? ` · ${formatDuration(exec.started_at, exec.completed_at)}`
            : ' · in progress'}
        </div>
      )}
      {exec.error_message && expanded && (
        <pre className="mt-1 p-2 bg-gray-900 rounded text-red-400 whitespace-pre-wrap break-words text-xs max-h-60 overflow-auto">
          {exec.error_message}
        </pre>
      )}
    </div>
  );
}

export function StageStatusList({ executions, projectId }: { executions: StageExecution[]; projectId?: string }) {
  if (executions.length === 0) return null;

  // Group by stage_key
  const grouped = executions.reduce((acc, e) => {
    if (!acc[e.stage_key]) acc[e.stage_key] = [];
    acc[e.stage_key].push(e);
    return acc;
  }, {} as Record<string, StageExecution[]>);

  return (
    <div className="space-y-2">
      <h4 className="text-sm font-semibold text-gray-300">Stage Executions</h4>
      {Object.entries(grouped).map(([stageKey, execs]) => (
        <div key={stageKey} className="bg-gray-800 rounded p-2">
          <div className="text-sm font-medium text-white mb-1">
            {stageKey.replace(/_/g, ' ')}
          </div>
          <div className="space-y-1">
            {execs.map((exec) => (
              <ExecutionRow key={exec.id} exec={exec} projectId={projectId} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
