import type { StructureNode } from '../api/structure';
import { useProjectStructure } from '../hooks/queries/useProjectStructure';
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
 *
 * Derived from the project-wide structure snapshot — no
 * per-component GET. Received resps come from decomposition
 * edges (source=resp, target=this comp); computed subresps are
 * resp-tier nodes with ``parent_id`` equal to this comp. Content
 * is included inline on the structure response for these "light"
 * tiers.
 */
export function ResponsibilityCoverage({ projectId, compId }: Props) {
  const { data, error, isLoading } = useProjectStructure(projectId);

  if (isLoading) {
    return <div className="p-4 text-xs text-gray-500">Loading responsibilities…</div>;
  }
  if (error) {
    return (
      <div className="p-4 text-xs text-red-400">
        {describeApiError(error, 'Failed to load responsibilities')}
      </div>
    );
  }
  if (!data) return null;

  // Received: top-level resp nodes connected to this comp via a
  // decomposition edge with ``target_id == compId``.
  const nodesById = new Map(data.nodes.map((n) => [n.id, n]));
  const receivedRespIds = new Set(
    data.edges
      .filter((e) => e.edge_type === 'decomposition' && e.target_id === compId)
      .map((e) => e.source_id),
  );
  const received = data.nodes
    .filter(
      (n) =>
        n.tier === 'resp' &&
        n.parent_id === null &&
        receivedRespIds.has(n.id),
    )
    .sort((a, b) => a.display_order - b.display_order);

  // Computed: subresps are resp-tier nodes parented to this comp.
  const computed = data.nodes
    .filter((n) => n.tier === 'resp' && n.parent_id === compId)
    .sort((a, b) => a.display_order - b.display_order);

  // The owning subreqs node lets us tell apart the three empty-
  // computed cases: (1) subreqs not approved yet → expected,
  // (2) subreqs approved but mint produced no subresps → bug,
  // (3) subreqs node missing entirely → upstream not bootstrapped.
  // Without this discrimination the user sees a generic "approve
  // the draft" hint even when the draft IS approved and something
  // downstream broke.
  const subreqsNode = data.nodes.find(
    (n) => n.tier === 'subreqs' && n.parent_id === compId,
  );
  const subreqsApproved = subreqsNode?.has_content ?? false;
  const computedEmptyHint = !subreqsNode
    ? 'No subrequirements node yet — sysarch must be approved before this component can decompose.'
    : subreqsApproved
      ? "Subrequirements is approved but no subresponsibilities were minted. " +
        "This is unexpected — check the v2.mint_subrequirements job logs " +
        "for parse / coverage failures."
      : 'No subresponsibilities yet. Approve the subrequirements draft to mint them.';

  // Silence lint: nodesById is kept to make subtree walks easy
  // for future enhancements (e.g. showing feature-of-origin for
  // each received resp).
  void nodesById;

  return (
    <section className="p-4 border-b border-gray-800 bg-gray-900/30">
      <h3 className="text-xs font-bold uppercase tracking-wide text-gray-400 mb-3">
        Responsibilities
      </h3>
      <div className="grid md:grid-cols-2 gap-4">
        <ResponsibilityList
          heading="Received"
          subheading="Routed here from sysarch — what this component was asked to own."
          items={received}
          emptyHint="No top-level responsibilities assigned to this component yet."
        />
        <ResponsibilityList
          heading="Computed"
          subheading="Produced by subreqs — how the component broke its received responsibilities down."
          items={computed}
          emptyHint={computedEmptyHint}
          warn={subreqsApproved && computed.length === 0}
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
  warn = false,
}: {
  heading: string;
  subheading: string;
  items: StructureNode[];
  emptyHint: string;
  warn?: boolean;
}) {
  return (
    <div>
      <h4 className="text-sm font-semibold text-gray-200 mb-0.5">
        {heading}
        <span className="ml-2 text-xs text-gray-500 font-normal">{items.length}</span>
      </h4>
      <p className="text-xs text-gray-500 mb-2">{subheading}</p>
      {items.length === 0 ? (
        <p
          className={
            warn
              ? 'text-xs text-amber-400 border-l-2 border-amber-700 pl-2'
              : 'text-xs italic text-gray-500'
          }
        >
          {emptyHint}
        </p>
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
