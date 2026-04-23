import { useState } from 'react';

/**
 * One-line card for an atomic ``<responsibility>``. The atom name
 * sits on the left; feat tags are collapsed to a count pill on
 * the right and expand inline on click. Kept in its own file so
 * fast-refresh can hot-reload the component without fighting the
 * renderer-map factory in ``requirementsRenderers.tsx``.
 */
export function ResponsibilityCard({
  name,
  feats,
  featureNames,
}: {
  name: string;
  feats: string[];
  featureNames: Record<string, string>;
}) {
  const [expanded, setExpanded] = useState(false);
  const count = feats.length;
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded border border-gray-700/60 bg-gray-900/40 px-3 py-2">
      <span className="text-sm text-gray-100">{name}</span>
      {count > 0 && (
        <>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            aria-label={
              expanded
                ? `Hide ${count} feature tag${count === 1 ? '' : 's'}`
                : `Show ${count} feature tag${count === 1 ? '' : 's'}`
            }
            className="rounded bg-gray-800/80 px-1.5 py-0.5 text-xs text-gray-400 hover:bg-gray-700/80 hover:text-gray-200"
          >
            {expanded ? '−' : '+'} {count} feat{count === 1 ? '' : 's'}
          </button>
          {expanded && (
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
    </div>
  );
}
