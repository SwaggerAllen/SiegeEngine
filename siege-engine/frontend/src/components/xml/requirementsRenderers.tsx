import type { XmlElement, XmlRendererMap } from './types';
import { findChild, findChildText, findChildren } from './types';

/**
 * Renderer overrides for the atomic requirements grammar:
 *
 *   <requirements>
 *     <responsibility>
 *       <name>session-state lifecycle</name>
 *       <feats>
 *         <feat id="feat_login01"/>
 *       </feats>
 *     </responsibility>
 *   </requirements>
 *
 * Each atom renders as a one-line bordered card — the name on
 * the left, a flex-wrap list of feat tags on the right. Feature
 * IDs resolve to ``name (feat_xxxxxxxx)`` when the caller
 * supplies a feature name map; otherwise the raw id appears.
 */
export function makeRequirementsRenderers(
  featureNames: Record<string, string> = {}
): XmlRendererMap {
  return {
    requirements: (node, ctx) => (
      <div className="not-prose space-y-2">{ctx.renderChildren(node.children)}</div>
    ),

    responsibility: (node) => {
      const name = findChildText(node, 'name') ?? 'Untitled';
      const feats = collectFeatIds(node);
      return (
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded border border-gray-700/60 bg-gray-900/40 px-3 py-2">
          <span className="text-sm text-gray-100">{name}</span>
          {feats.length > 0 && (
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
        </div>
      );
    },

    // Structured children consumed by the <responsibility>
    // renderer above. Render nothing if they bubble up on their
    // own (schema drift — validator would reject).
    name: () => null,
    feats: () => null,
    feat: () => null,
  };
}

function collectFeatIds(responsibility: XmlElement): string[] {
  const block = findChild(responsibility, 'feats');
  if (!block) return [];
  return findChildren(block, 'feat')
    .map((f) => (typeof f.attributes.id === 'string' ? f.attributes.id : null))
    .filter((id): id is string => id !== null);
}

/**
 * Back-compat module-level export: a renderer map with no
 * feature-name resolution. Existing callers (tests, non-panel
 * usages) get bare feat IDs; the dashboard's ``RequirementsPanel``
 * opts into the factory form so its cards can show names.
 */
export const requirementsRenderers: XmlRendererMap = makeRequirementsRenderers();
