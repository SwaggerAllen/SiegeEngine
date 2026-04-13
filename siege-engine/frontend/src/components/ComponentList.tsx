import { useComponents } from '../hooks/queries/useSysarchQueries';
import { describeApiError } from '../lib/describeApiError';

interface Props {
  projectId: string;
  /**
   * True if the sysarch node has been approved but the
   * ``v2.mint_sysarch`` handler might still be producing comp_*
   * nodes. Same polling pattern as FeatureList and ResponsibilityList.
   */
  mintPending: boolean;
}

export function ComponentList({ projectId, mintPending }: Props) {
  const { data, error, isLoading } = useComponents(projectId, mintPending);

  if (isLoading) {
    return <div className="p-6 text-gray-400 text-sm">Loading components…</div>;
  }
  if (error) {
    return (
      <div className="p-6 text-red-400 text-sm">
        {describeApiError(error, 'Failed to load components')}
      </div>
    );
  }
  if (!data) return null;

  const components = data.components;

  if (components.length === 0) {
    return (
      <div className="p-6 space-y-2">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
          Top-level Components
        </h3>
        <p className="text-sm text-gray-500 italic">
          {mintPending
            ? 'Minting components from the approved system architecture…'
            : 'No components yet.'}
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
        Top-level Components ({components.length})
      </h3>
      <ul className="grid gap-3 md:grid-cols-2">
        {components.map((comp) => (
          <li
            key={comp.id}
            className="bg-gray-800/50 border border-gray-700 rounded p-4 space-y-1"
          >
            <div className="flex items-baseline justify-between gap-2">
              <h5 className="font-semibold text-white">{comp.name}</h5>
              <div className="flex items-center gap-2">
                <span
                  className={
                    'text-xs uppercase tracking-wider px-1.5 py-0.5 rounded ' +
                    (comp.kind === 'presentational'
                      ? 'bg-purple-900/40 text-purple-200'
                      : 'bg-blue-900/40 text-blue-200')
                  }
                >
                  {comp.kind}
                </span>
                <span className="text-xs text-gray-500 tabular-nums">
                  #{comp.display_order}
                </span>
              </div>
            </div>
            <div className="text-[10px] font-mono text-gray-500">{comp.id}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
