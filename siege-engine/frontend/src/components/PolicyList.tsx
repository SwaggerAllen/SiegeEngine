import { usePolicies } from '../hooks/queries/useSysarchQueries';
import { describeApiError } from '../lib/describeApiError';
import { parseXml } from './xml/parser';
import { findChildText } from './xml/types';

interface Props {
  projectId: string;
  mintPending: boolean;
}

interface ParsedPolicy {
  id: string;
  name: string;
  trigger: string;
  required: string;
  rationale: string;
}

function parsePolicyBlob(id: string, name: string, blob: string): ParsedPolicy {
  try {
    const root = parseXml(blob);
    return {
      id,
      name,
      trigger: findChildText(root, 'trigger') ?? '',
      required: findChildText(root, 'required') ?? '',
      rationale: findChildText(root, 'rationale') ?? '',
    };
  } catch {
    return { id, name, trigger: '', required: '', rationale: blob };
  }
}

export function PolicyList({ projectId, mintPending }: Props) {
  const { data, error, isLoading } = usePolicies(projectId, mintPending);

  if (isLoading) {
    return <div className="p-6 text-gray-400 text-sm">Loading policies…</div>;
  }
  if (error) {
    return (
      <div className="p-6 text-red-400 text-sm">
        {describeApiError(error, 'Failed to load policies')}
      </div>
    );
  }
  if (!data) return null;

  const parsed = data.policies.map((p) => parsePolicyBlob(p.id, p.name, p.content));

  if (parsed.length === 0) {
    return (
      <div className="p-6 space-y-2">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
          Top-level Policies
        </h3>
        <p className="text-sm text-gray-500 italic">
          {mintPending
            ? 'Minting policies from the approved system architecture…'
            : 'No policies yet.'}
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
        Top-level Policies ({parsed.length})
      </h3>
      <ul className="space-y-2 list-none p-0">
        {parsed.map((policy) => (
          <li
            key={policy.id}
            className="bg-gray-800/50 border border-gray-700 rounded p-4 space-y-1"
          >
            <div className="flex items-baseline flex-wrap gap-x-2 gap-y-1">
              <h5 className="font-semibold text-white m-0 text-sm">{policy.name}</h5>
              {policy.trigger && (
                <span className="text-xs italic text-gray-400">on {policy.trigger}</span>
              )}
            </div>
            {policy.required && (
              <div className="text-xs text-gray-400">
                requires{' '}
                <span className="font-mono text-gray-300">{policy.required}</span>
              </div>
            )}
            {policy.rationale && (
              <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
                {policy.rationale}
              </p>
            )}
            <div className="text-[10px] font-mono text-gray-500">{policy.id}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
