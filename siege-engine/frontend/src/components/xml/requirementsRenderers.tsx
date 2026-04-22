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
 *       <owns>
 *         <feat id="feat_abc12345"/>
 *       </owns>
 *       <supports>
 *         <feat id="feat_def67890"/>
 *       </supports>
 *     </responsibility>
 *     …
 *   </requirements>
 *
 * Every responsibility becomes a bordered card with a name
 * heading, the paragraph-length intent, and two distinct footer
 * sections when present: "Owns" (features this responsibility is
 * the primary system-side owner of — single-owner rule guarantees
 * each feature appears in exactly one responsibility's owns block
 * across the doc) and "Supports" (features this responsibility
 * contributes to without owning; many-to-many). Feature IDs
 * resolve to ``name (feat_xxxxxxxx)`` when the caller supplies a
 * feature name map, or render as bare IDs when it doesn't.
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
      const collectIds = (container: typeof node | undefined) =>
        container
          ? findChildren(container, 'feat')
              .map((f) => (typeof f.attributes.id === 'string' ? f.attributes.id : null))
              .filter((id): id is string => id !== null)
          : [];
      const ownedIds = collectIds(findChild(node, 'owns'));
      const supportedIds = collectIds(findChild(node, 'supports'));
      const totalCount = ownedIds.length + supportedIds.length;
      const meta =
        totalCount > 0 ? (
          <span className="text-gray-500">
            {ownedIds.length} owns
            {supportedIds.length > 0 ? ` · ${supportedIds.length} supports` : ''}
          </span>
        ) : undefined;
      const renderFeatureList = (
        heading: string,
        tone: 'owned' | 'supported',
        ids: string[],
      ) => {
        const headingTone =
          tone === 'owned' ? 'text-emerald-400/80' : 'text-blue-400/70';
        return (
          <div className="pt-1 border-t border-gray-700/60">
            <div
              className={`text-xs uppercase tracking-wider mb-1 ${headingTone}`}
            >
              {heading}
            </div>
            <ul className="text-xs text-gray-400 space-y-0.5">
              {ids.map((fid) => (
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
        );
      };
      return (
        <CollapsibleSection summary={name} meta={meta}>
          {intent && <p className="text-sm text-gray-300 m-0">{intent}</p>}
          {ownedIds.length > 0 && renderFeatureList('Owns', 'owned', ownedIds)}
          {supportedIds.length > 0 &&
            renderFeatureList('Supports', 'supported', supportedIds)}
        </CollapsibleSection>
      );
    },

    // <name>, <intent>, <owns>, and <supports> are consumed by the
    // <responsibility> renderer above. Render nothing if they bubble
    // up on their own (schema drift — the validator would reject
    // it, but defense in depth).
    name: () => null,
    intent: () => null,
    owns: () => null,
    supports: () => null,
  };
}

/**
 * Back-compat module-level export: a renderer map with no
 * feature-name resolution. Existing callers (tests, non-panel
 * usages) get bare feat IDs; the dashboard's ``RequirementsPanel``
 * opts into the factory form so its cards can show names.
 */
export const requirementsRenderers: XmlRendererMap = makeRequirementsRenderers();
