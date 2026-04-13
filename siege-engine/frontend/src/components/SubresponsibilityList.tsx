import { useSubresponsibilities } from '../hooks/queries/useSubreqsQueries';
import { describeApiError } from '../lib/describeApiError';

interface Props {
  projectId: string;
  componentId: string;
  mintPending: boolean;
}

export function SubresponsibilityList({
  projectId,
  componentId,
  mintPending,
}: Props) {
  const { data, error, isLoading } = useSubresponsibilities(
    projectId,
    componentId,
    mintPending
  );

  if (isLoading) {
    return (
      <div className="p-6 text-gray-400 text-sm">Loading subresponsibilities…</div>
    );
  }
  if (error) {
    return (
      <div className="p-6 text-red-400 text-sm">
        {describeApiError(error, 'Failed to load subresponsibilities')}
      </div>
    );
  }
  if (!data) return null;

  const subresps = data.subresponsibilities;

  if (subresps.length === 0) {
    return (
      <div className="p-6 space-y-2">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
          Subresponsibilities
        </h3>
        <p className="text-sm text-gray-500 italic">
          {mintPending
            ? 'Minting subresponsibilities from the approved draft…'
            : 'No subresponsibilities yet.'}
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
        Subresponsibilities ({subresps.length})
      </h3>
      <ul className="grid gap-3 md:grid-cols-2">
        {subresps.map((resp) => (
          <li
            key={resp.id}
            className="bg-gray-800/50 border border-gray-700 rounded p-4 space-y-2"
          >
            <div className="flex items-baseline justify-between gap-2">
              <h5 className="font-semibold text-white">{resp.name}</h5>
              <span className="text-xs text-gray-500 tabular-nums">
                #{resp.display_order}
              </span>
            </div>
            <p className="text-sm text-gray-300 line-clamp-4">{resp.content}</p>
            <div className="text-[10px] font-mono text-gray-500">{resp.id}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
