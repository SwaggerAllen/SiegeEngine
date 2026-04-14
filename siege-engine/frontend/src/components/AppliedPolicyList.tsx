import { useAppliedPolicies } from '../hooks/queries/useComparchQueries';
import { describeApiError } from '../lib/describeApiError';
import { parseXml } from './xml/parser';
import { findChildText } from './xml/types';

interface Props {
  projectId: string;
  componentId: string;
}

/**
 * Lists the policies that have already been applied to this
 * component via ``policy_application`` edges. Includes both
 * top-level policies applied by the stage 5 pass and, once the
 * stage 6 pass runs on subcomponents, component-local policies
 * that apply to this component too.
 *
 * Rationale from the LLM's decision is not shown — per the
 * Phase 4 stage 9 design call, rationale stays in handler logs
 * only.
 */
export function AppliedPolicyList({ projectId, componentId }: Props) {
  const { data, error, isLoading } = useAppliedPolicies(projectId, componentId);

  if (isLoading) {
    return <div className="p-6 text-gray-400 text-sm">Loading applied policies…</div>;
  }
  if (error) {
    return (
      <div className="p-6 text-red-400 text-sm">
        {describeApiError(error, 'Failed to load applied policies')}
      </div>
    );
  }
  if (!data) return null;

  const applied = data.applied_policies;

  if (applied.length === 0) {
    return (
      <div className="p-6 space-y-2">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
          Applied Policies
        </h3>
        <p className="text-sm text-gray-500 italic">
          No policies have been applied to this component yet.
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
        Applied Policies ({applied.length})
      </h3>
      <ul className="space-y-2 list-none p-0">
        {applied.map((row) => {
          let trigger = '';
          let required = '';
          try {
            const tree = parseXml(row.policy_content);
            trigger = findChildText(tree, 'trigger') ?? '';
            required = findChildText(tree, 'required') ?? '';
          } catch {
            // Malformed blob — just show the name.
          }
          return (
            <li
              key={row.policy_id}
              className="bg-gray-800/50 border border-gray-700 rounded p-4 space-y-1"
            >
              <div className="flex items-baseline flex-wrap gap-x-2 gap-y-1">
                <h5 className="font-semibold text-white m-0 text-sm">
                  {row.policy_name}
                </h5>
                {trigger && (
                  <span className="text-xs italic text-gray-400">on {trigger}</span>
                )}
              </div>
              {required && (
                <div className="text-xs text-gray-400">
                  requires <span className="font-mono text-gray-300">{required}</span>
                </div>
              )}
              <div className="text-[10px] font-mono text-gray-500">
                {row.policy_id}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
