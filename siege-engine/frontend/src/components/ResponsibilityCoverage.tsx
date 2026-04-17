import type { ResponsibilitySummary } from '../api/responsibilityCoverage';
import { useResponsibilityCoverage } from '../hooks/queries/useResponsibilityCoverage';
import { describeApiError } from '../lib/describeApiError';

interface Props {
  projectId: string;
  compId: string;
}

/**
 * Side-by-side view of a component's responsibility coverage.
 *
 * "Received" lists the top-level resps routed to this component
 * via sysarch decomposition edges — what the component was told
 * to own. "Computed" lists the subresps the component produced
 * at subreqs approval time — how it broke those received
 * responsibilities into units that get assigned to
 * subcomponents at comparch time. Seeing both together lets the
 * user audit the compression: is every received resp covered by
 * the computed set? Did the component over- or under-decompose?
 */
export function ResponsibilityCoverage({ projectId, compId }: Props) {
  const { data, error, isLoading } = useResponsibilityCoverage(projectId, compId);

  if (isLoading) {
    return (
      <div className="p-4 text-xs text-gray-500">Loading responsibilities…</div>
    );
  }
  if (error) {
    return (
      <div className="p-4 text-xs text-red-400">
        {describeApiError(error, 'Failed to load responsibilities')}
      </div>
    );
  }
  if (!data) return null;

  return (
    <section className="p-4 border-b border-gray-800 bg-gray-900/30">
      <h3 className="text-xs font-bold uppercase tracking-wide text-gray-400 mb-3">
        Responsibilities
      </h3>
      <div className="grid md:grid-cols-2 gap-4">
        <ResponsibilityList
          heading="Received"
          subheading="Routed here from sysarch — what this component was asked to own."
          items={data.received}
          emptyHint="No top-level responsibilities assigned to this component yet."
        />
        <ResponsibilityList
          heading="Computed"
          subheading="Produced by subreqs — how the component broke its received responsibilities down."
          items={data.computed}
          emptyHint="No subresponsibilities yet. Approve the subrequirements draft to mint them."
        />
      </div>
    </section>
  );
}

function ResponsibilityList({
  heading,
  subheading,
  items,
  emptyHint,
}: {
  heading: string;
  subheading: string;
  items: ResponsibilitySummary[];
  emptyHint: string;
}) {
  return (
    <div>
      <h4 className="text-sm font-semibold text-gray-200 mb-0.5">
        {heading}
        <span className="ml-2 text-xs text-gray-500 font-normal">
          {items.length}
        </span>
      </h4>
      <p className="text-xs text-gray-500 mb-2">{subheading}</p>
      {items.length === 0 ? (
        <p className="text-xs italic text-gray-500">{emptyHint}</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item) => (
            <li
              key={item.id}
              className="text-sm text-gray-300 border-l-2 border-gray-700 pl-2"
            >
              <div className="font-medium text-gray-100">
                {item.name}{' '}
                <span className="ml-1 text-[10px] text-gray-500 font-mono">
                  {item.id}
                </span>
              </div>
              {item.content && (
                <p className="text-xs text-gray-400 whitespace-pre-wrap mt-0.5">
                  {item.content}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
