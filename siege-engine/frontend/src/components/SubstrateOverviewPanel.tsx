import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import * as siegeApi from '../api/siege';
import type { BodyScope } from '../api/siege';
import type { StructureNode } from '../api/structure';
import { SYNTHETIC_IDS } from './nav/buildNavTree';

interface Props {
  projectId: string;
  /** One of the substrate-root SYNTHETIC_IDS values; selects which
   *  per-tier slice of ``nodes`` to render. */
  substrateId:
    | typeof SYNTHETIC_IDS.FEATURE_EXPANSION
    | typeof SYNTHETIC_IDS.REQUIREMENTS
    | typeof SYNTHETIC_IDS.SYSARCH;
  nodes: StructureNode[];
}

const CONFIG = {
  [SYNTHETIC_IDS.FEATURE_EXPANSION]: {
    label: 'Feature Expansion',
    itemLabel: 'feature',
    matches: (n: StructureNode) => n.tier === 'feat',
    bodyScope: { tier: 'feature_expansion', comp_id: 'proj' } as BodyScope,
  },
  [SYNTHETIC_IDS.REQUIREMENTS]: {
    label: 'Requirements',
    itemLabel: 'responsibility',
    matches: (n: StructureNode) => n.tier === 'resp',
    bodyScope: { tier: 'requirements', comp_id: 'proj' } as BodyScope,
  },
  [SYNTHETIC_IDS.SYSARCH]: {
    label: 'Sysarch',
    itemLabel: 'component',
    matches: (n: StructureNode) => n.tier === 'comp' && n.parent_id === null,
    bodyScope: { tier: 'sysarch', comp_id: 'proj' } as BodyScope,
  },
} as const;

/**
 * Read-only substrate-root overview. Renders the list of per-item
 * nodes (features / responsibilities / top-level components) that
 * belong to the selected substrate so the sidebar's "Feature
 * Expansion" / "Requirements" / "Sysarch" entries land somewhere
 * useful for upload-imported projects.
 *
 * Upload projects don't carry the legacy substrate-root row that
 * the rich editor panels (FeatureExpansionPanel, RequirementsPanel,
 * SysarchPanel) need, so we surface what we have — the per-item
 * nodes — and let the user drill into the DAG for the full picture.
 */
export function SubstrateOverviewPanel({ projectId, substrateId, nodes }: Props) {
  const navigate = useNavigate();
  const config = CONFIG[substrateId];
  const items = nodes
    .filter(config.matches)
    .slice()
    .sort((a, b) => a.display_order - b.display_order);
  const body = useQuery({
    queryKey: ['v3-body', projectId, config.bodyScope],
    queryFn: () => siegeApi.getBody(projectId, config.bodyScope),
  });

  return (
    <div
      className="h-full overflow-auto p-4 space-y-4"
      data-testid={`substrate-overview-${substrateId}`}
    >
      <header className="space-y-1">
        <h2 className="text-lg font-semibold text-gray-100">{config.label}</h2>
        <p className="text-xs text-gray-500">
          {items.length} {config.itemLabel}
          {items.length === 1 ? '' : 's'} — read-only overview from the imported
          substrate. Open the{' '}
          <button
            type="button"
            className="text-cyan-300 hover:text-cyan-200 underline"
            onClick={() => navigate(`/projects/${projectId}?node=${SYNTHETIC_IDS.DAG}`)}
          >
            decomposition graph
          </button>{' '}
          to see how they connect.
        </p>
      </header>
      {items.length === 0 ? (
        <div className="text-xs text-gray-500 italic">
          No {config.itemLabel}s found in this substrate.
        </div>
      ) : (
        <ul className="space-y-1">
          {items.map((n) => (
            <li
              key={n.id}
              className="rounded border border-gray-800 bg-gray-950/40 px-3 py-2 text-sm text-gray-200"
              data-testid={`substrate-overview-${substrateId}-row-${n.id}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate">{n.name || n.id}</span>
                <span className="font-mono text-[10px] text-gray-500">{n.id}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
      <section className="space-y-1">
        <h3 className="text-sm font-semibold text-gray-200">Substrate body</h3>
        {body.data?.body_path && (
          <p className="font-mono text-[11px] text-gray-600">
            {body.data.body_path}
          </p>
        )}
        {body.isLoading && (
          <p className="text-xs text-gray-500 italic">Loading body…</p>
        )}
        {body.data && !body.isLoading && !body.data.found && (
          <p className="text-xs text-gray-500 italic">
            No body drafted for this substrate yet.
          </p>
        )}
        {body.data && body.data.found && (
          <pre className="whitespace-pre-wrap break-words rounded border border-gray-800 bg-gray-950/60 p-3 text-xs text-gray-200 font-mono leading-relaxed">
            {body.data.body_text}
          </pre>
        )}
      </section>
    </div>
  );
}
