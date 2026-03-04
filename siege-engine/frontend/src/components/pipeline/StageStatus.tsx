import type { StageExecution } from '../../types/pipeline';

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

export function StageStatusList({ executions }: { executions: StageExecution[] }) {
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
            {execs.map((exec) => {
              const badge = STATUS_BADGES[exec.status] || STATUS_BADGES.pending;
              return (
                <div key={exec.id} className="flex items-center gap-2 text-xs">
                  <span className={`px-1.5 py-0.5 rounded text-white ${badge.bg}`}>
                    {badge.text}
                  </span>
                  {exec.component_key && (
                    <span className="text-gray-400">{exec.component_key}</span>
                  )}
                  {exec.error_message && (
                    <span className="text-red-400 truncate">{exec.error_message}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
