import { CollapsibleSection } from './CollapsibleSection';
import type { XmlRendererMap } from './types';
import { findChild, findChildText, findChildren } from './types';

/**
 * Renderer overrides for the requirements schema:
 *
 *   <requirements>
 *     <responsibility>
 *       <name>Authentication</name>
 *       <intent>…</intent>
 *       <covers>
 *         <feat id="feat_abc12345"/>
 *         <feat id="feat_def67890"/>
 *       </covers>
 *     </responsibility>
 *     …
 *   </requirements>
 *
 * Every responsibility becomes a bordered card with a name heading,
 * the paragraph-length intent, and a "Covers" footer that lists the
 * upstream features this responsibility decomposes — each rendered
 * as ``name (feat_xxxxxxxx)`` when the caller supplies a feature
 * name map, or as a bare id when it doesn't.
 *
 * Shape is parallel to ``featureRenderers``. The factory form lets
 * the owning panel (``RequirementsPanel``) close over the live
 * feature list query so responsibility cards can resolve feat IDs
 * into human-readable names without the XML walker itself needing
 * a generic "extra context" plumbing slot.
 */
export function makeRequirementsRenderers(
  featureNames: Record<string, string> = {}
): XmlRendererMap {
  return {
    requirements: (node, ctx) => (
      <div className="not-prose space-y-3">{ctx.renderChildren(node.children)}</div>
    ),

    responsibility: (node) => {
      const name = findChildText(node, 'name') ?? 'Untitled';
      const intent = findChildText(node, 'intent') ?? '';
      const coversElement = findChild(node, 'covers');
      const coveredFeatureIds = coversElement
        ? findChildren(coversElement, 'feat')
            .map((f) => (typeof f.attributes.id === 'string' ? f.attributes.id : null))
            .filter((id): id is string => id !== null)
        : [];
      const meta =
        coveredFeatureIds.length > 0 ? (
          <span className="text-gray-500">{coveredFeatureIds.length} feat</span>
        ) : undefined;
      return (
        <CollapsibleSection summary={name} meta={meta}>
          {intent && <p className="text-sm text-gray-300 m-0">{intent}</p>}
          {coveredFeatureIds.length > 0 && (
            <div className="pt-1 border-t border-gray-700/60">
              <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">
                Covers
              </div>
              <ul className="text-xs text-gray-400 space-y-0.5">
                {coveredFeatureIds.map((fid) => (
                  <li key={fid} className="font-mono">
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
            </div>
          )}
        </CollapsibleSection>
      );
    },

    // <name>, <intent>, and <covers> are consumed by the
    // <responsibility> renderer above. Render nothing if they bubble
    // up on their own (schema drift — the validator would reject it,
    // but defense in depth).
    name: () => null,
    intent: () => null,
    covers: () => null,
  };
}

/**
 * Back-compat module-level export: a renderer map with no
 * feature-name resolution. Existing callers (tests, non-panel
 * usages) get bare feat IDs; the dashboard's ``RequirementsPanel``
 * opts into the factory form so its cards can show names.
 */
export const requirementsRenderers: XmlRendererMap = makeRequirementsRenderers();
