import { useSubcomponents } from '../hooks/queries/useComparchQueries';
import { describeApiError } from '../lib/describeApiError';

interface Props {
  projectId: string;
  componentId: string;
  mintPending: boolean;
}

export function SubcomponentList({ projectId, componentId, mintPending }: Props) {
  const { data, error, isLoading } = useSubcomponents(
    projectId,
    componentId,
    mintPending
  );

  if (isLoading) {
    return <div className="p-6 text-gray-400 text-sm">Loading subcomponents…</div>;
  }
  if (error) {
    return (
      <div className="p-6 text-red-400 text-sm">
        {describeApiError(error, 'Failed to load subcomponents')}
      </div>
    );
  }
  if (!data) return null;

  const subs = data.subcomponents;

  if (subs.length === 0) {
    return (
      <div className="p-6 space-y-2">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
          Subcomponents
        </h3>
        <p className="text-sm text-gray-500 italic">
          {mintPending
            ? 'Minting subcomponents from the approved architecture doc…'
            : 'Un-fanned-out: this component does not decompose into subcomponents.'}
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
        Subcomponents ({subs.length})
      </h3>
      <ul className="grid gap-3 md:grid-cols-2">
        {subs.map((sub) => (
          <li
            key={sub.id}
            className="bg-gray-800/50 border border-gray-700 rounded p-4 space-y-1"
          >
            <div className="flex items-baseline justify-between gap-2">
              <h5 className="font-semibold text-white">{sub.name}</h5>
              <span className="text-xs text-gray-500 tabular-nums">
                #{sub.display_order}
              </span>
            </div>
            <div className="text-[10px] font-mono text-gray-500">{sub.id}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
