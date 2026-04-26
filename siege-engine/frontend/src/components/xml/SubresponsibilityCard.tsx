import { useState } from 'react';

/**
 * One-line card for an atomic ``<subresponsibility>``. Mirrors
 * ``ResponsibilityCard`` but carries an additional ``derived-from``
 * pill so the parent resp IDs this subresp decomposes stay
 * visible alongside the feat tags. Two collapsible count pills:
 * one for feats (left), one for parent resps (right).
 */
export function SubresponsibilityCard({
  name,
  feats,
  parentIds,
  featureNames,
  parentNames = {},
}: {
  name: string;
  feats: string[];
  parentIds: string[];
  featureNames: Record<string, string>;
  /** Optional ``resp_id → display name`` map. When supplied,
   * each parent-resp chip renders ``Name (resp_xxx)``. Without
   * it, chips show the raw id (back-compat for callers that
   * don't have the structure snapshot loaded yet). */
  parentNames?: Record<string, string>;
}) {
  const [featsExpanded, setFeatsExpanded] = useState(false);
  const [parentsExpanded, setParentsExpanded] = useState(false);
  const featCount = feats.length;
  const parentCount = parentIds.length;
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded border border-gray-700/60 bg-gray-900/40 px-3 py-2">
      <span className="text-sm text-gray-100">{name}</span>
      {featCount > 0 && (
        <>
          <button
            type="button"
            onClick={() => setFeatsExpanded((v) => !v)}
            aria-expanded={featsExpanded}
            aria-label={
              featsExpanded
                ? `Hide ${featCount} feature tag${featCount === 1 ? '' : 's'}`
                : `Show ${featCount} feature tag${featCount === 1 ? '' : 's'}`
            }
            className="rounded bg-gray-800/80 px-1.5 py-0.5 text-xs text-gray-400 hover:bg-gray-700/80 hover:text-gray-200"
          >
            {featsExpanded ? '−' : '+'} {featCount} feat{featCount === 1 ? '' : 's'}
          </button>
          {featsExpanded && (
            <ul className="flex flex-wrap gap-1.5 text-xs">
              {feats.map((fid) => (
                <li
                  key={fid}
                  className="rounded bg-gray-800/80 px-1.5 py-0.5 font-mono text-gray-300"
                >
                  {featureNames[fid] ? (
                    <>
                      <span className="text-gray-200">{featureNames[fid]}</span>{' '}
                      <span className="text-gray-500">({fid})</span>
                    </>
                  ) : (
                    fid
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {parentCount > 0 && (
        <>
          <button
            type="button"
            onClick={() => setParentsExpanded((v) => !v)}
            aria-expanded={parentsExpanded}
            aria-label={
              parentsExpanded
                ? `Hide ${parentCount} parent responsibilit${parentCount === 1 ? 'y' : 'ies'}`
                : `Show ${parentCount} parent responsibilit${parentCount === 1 ? 'y' : 'ies'}`
            }
            className="rounded bg-gray-800/80 px-1.5 py-0.5 text-xs text-gray-400 hover:bg-gray-700/80 hover:text-gray-200"
          >
            {parentsExpanded ? '−' : '+'} {parentCount} parent
            {parentCount === 1 ? '' : 's'}
          </button>
          {parentsExpanded && (
            <ul className="flex flex-wrap gap-1.5 text-xs">
              {parentIds.map((pid) => (
                <li
                  key={pid}
                  className="rounded bg-gray-800/80 px-1.5 py-0.5 font-mono text-gray-300"
                >
                  {parentNames[pid] ? (
                    <>
                      <span className="text-gray-200">{parentNames[pid]}</span>{' '}
                      <span className="text-gray-500">({pid})</span>
                    </>
                  ) : (
                    pid
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
