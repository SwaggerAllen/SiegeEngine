import { useResponsibilities } from '../hooks/queries/useRequirementsQueries';
import { describeApiError } from '../lib/describeApiError';

interface Props {
  projectId: string;
  /**
   * True if the reqs node has been approved but the
   * ``v2.mint_requirements`` handler might still be producing
   * resp_* nodes. Triggers polling until the list becomes
   * non-empty. Same shape as FeatureList's ``mintPending``.
   */
  mintPending: boolean;
}

export function ResponsibilityList({ projectId, mintPending }: Props) {
  const { data, error, isLoading } = useResponsibilities(projectId, mintPending);

  if (isLoading) {
    return <div className="p-6 text-gray-400 text-sm">Loading responsibilities…</div>;
  }
  if (error) {
    return (
      <div className="p-6 text-red-400 text-sm">
        {describeApiError(error, 'Failed to load responsibilities')}
      </div>
    );
  }
  if (!data) return null;

  const responsibilities = data.responsibilities;

  if (responsibilities.length === 0) {
    return (
      <div className="p-6 space-y-2">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
          Top-level Responsibilities
        </h3>
        <p className="text-sm text-gray-500 italic">
          {mintPending
            ? 'Minting responsibilities from the approved requirements…'
            : 'No responsibilities yet.'}
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
        Top-level Responsibilities ({responsibilities.length})
      </h3>
      <ul className="grid gap-3 md:grid-cols-2">
        {responsibilities.map((resp) => (
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
          </li>
        ))}
      </ul>
    </div>
  );
}
