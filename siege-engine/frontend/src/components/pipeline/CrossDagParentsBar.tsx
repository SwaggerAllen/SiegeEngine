import { useCrossDagStatus } from '../../hooks/queries/useDAGQueries';

const STATUS_COLORS: Record<string, string> = {
  approved: 'bg-green-500',
  awaiting_review: 'bg-yellow-500',
  generating: 'bg-blue-500 animate-pulse',
  running: 'bg-blue-500 animate-pulse',
  ai_reviewing: 'bg-purple-500 animate-pulse',
  pending: 'bg-gray-500',
  conditional: 'bg-gray-600',
  failed: 'bg-red-500',
};

export function CrossDagParentsBar({
  projectId,
  componentKey,
}: {
  projectId: string;
  componentKey: string;
}) {
  const { data: entries } = useCrossDagStatus(projectId);

  // Find the cross-DAG entry for this frontend component
  // componentKey may be "comp_key" or "comp_key.sub_key" — use root
  const rootKey = componentKey.split('.')[0];
  const entry = entries?.find((e) => e.frontend_component === rootKey);

  if (!entry || !entry.domain_parents.length) return null;

  return (
    <div className="px-3 py-2 bg-gray-800/60 border-b border-gray-700">
      <div className="text-xs text-gray-400 mb-1.5">Domain Parents</div>
      <div className="flex flex-wrap gap-2">
        {entry.domain_parents.map((dp) => (
          <div
            key={dp.key}
            className="flex items-center gap-1.5 px-2 py-0.5 bg-gray-700/60 rounded text-xs"
          >
            <span className={`w-1.5 h-1.5 rounded-full ${STATUS_COLORS[dp.architecture_status] ?? 'bg-gray-500'}`} />
            <span className="text-gray-300 font-mono">{dp.key}</span>
            <span className="text-gray-500">{dp.architecture_status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
