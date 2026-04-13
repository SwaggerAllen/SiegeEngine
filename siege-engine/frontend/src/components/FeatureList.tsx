import { useFeatures } from '../hooks/queries/useFeatureQueries';
import { describeApiError } from '../lib/describeApiError';

interface Props {
  projectId: string;
  /**
   * True if the expansion has been approved but the mint handler
   * might still be producing features. Triggers polling until the
   * list becomes non-empty.
   */
  mintPending: boolean;
}

export function FeatureList({ projectId, mintPending }: Props) {
  const { data, error, isLoading } = useFeatures(projectId, mintPending);

  if (isLoading) {
    return (
      <div className="p-6 text-gray-400 text-sm">Loading features…</div>
    );
  }
  if (error) {
    return (
      <div className="p-6 text-red-400 text-sm">
        {describeApiError(error, 'Failed to load features')}
      </div>
    );
  }
  if (!data) return null;

  const features = data.features;

  if (features.length === 0) {
    // Two reasons the list is empty:
    // 1. The mint is pending (we're polling).
    // 2. The expansion isn't approved yet, or the mint has already
    //    failed for some reason. In that case the user should see
    //    the expansion panel's state rather than this component,
    //    but we still render something sensible.
    return (
      <div className="p-6 space-y-2">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
          Features
        </h3>
        <p className="text-sm text-gray-500 italic">
          {mintPending
            ? 'Minting features from the approved expansion…'
            : 'No features yet.'}
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-3 max-w-4xl mx-auto">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
        Features ({features.length})
      </h3>
      <ul className="grid gap-3 md:grid-cols-2">
        {features.map((feature) => (
          <li
            key={feature.id}
            className="bg-gray-800/50 border border-gray-700 rounded p-4 space-y-2"
          >
            <div className="flex items-baseline justify-between gap-2">
              <h4 className="font-semibold text-white">{feature.name}</h4>
              <span className="text-xs text-gray-500 tabular-nums">
                #{feature.display_order}
              </span>
            </div>
            <p className="text-sm text-gray-300 line-clamp-4">
              {feature.content}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
