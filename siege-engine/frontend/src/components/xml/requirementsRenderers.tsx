import { CollapsibleSection } from './CollapsibleSection';
import type { XmlElement, XmlRendererMap } from './types';
import { findChild, findChildText, findChildren, textContent } from './types';

/**
 * Renderer overrides for the requirements schema:
 *
 *   <requirements>
 *     <responsibility>
 *       <name>Authentication</name>
 *       <scope>
 *         <item>session-state lifecycle</item>
 *         <item>password hash storage</item>
 *       </scope>
 *       <does-not-own>
 *         <defers to="Per-Request Authorization">permission checks</defers>
 *       </does-not-own>
 *       <failure-surface>Broken verifier blocks all sign-ins.</failure-surface>
 *       <owns>
 *         <feat id="feat_abc12345"/>
 *       </owns>
 *       <supports>
 *         <feat id="feat_def67890"/>
 *       </supports>
 *     </responsibility>
 *   </requirements>
 *
 * Each responsibility renders as a bordered card with the
 * structured fields laid out in read order: scope phrases as a
 * list, deferrals as a "defers to" list, the one-sentence failure
 * surface, and the owns / supports feature sections. Feature IDs
 * resolve to ``name (feat_xxxxxxxx)`` when the caller supplies a
 * feature name map.
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
      const scopeItems = collectScopeItems(node);
      const deferrals = collectDeferrals(node);
      const failureSurface = findChildText(node, 'failure-surface') ?? '';
      const collectIds = (container: XmlElement | undefined) =>
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
          {scopeItems.length > 0 && (
            <div className="pt-1">
              <div className="text-xs uppercase tracking-wider mb-1 text-gray-400">
                Scope
              </div>
              <ul className="text-sm text-gray-300 space-y-0.5 list-disc list-inside marker:text-gray-600">
                {scopeItems.map((phrase, i) => (
                  <li key={i}>{phrase}</li>
                ))}
              </ul>
            </div>
          )}
          {deferrals.length > 0 && (
            <div className="pt-1 border-t border-gray-700/60">
              <div className="text-xs uppercase tracking-wider mb-1 text-amber-400/70">
                Does not own
              </div>
              <ul className="text-xs text-gray-400 space-y-0.5">
                {deferrals.map((d, i) => (
                  <li key={i}>
                    <span className="text-gray-200">{d.scope}</span>{' '}
                    <span className="text-gray-500">→</span>{' '}
                    <span className="italic text-gray-300">{d.to}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {failureSurface && (
            <div className="pt-1 border-t border-gray-700/60">
              <div className="text-xs uppercase tracking-wider mb-1 text-red-400/70">
                Failure surface
              </div>
              <p className="text-xs text-gray-300 m-0 italic">{failureSurface}</p>
            </div>
          )}
          {ownedIds.length > 0 && renderFeatureList('Owns', 'owned', ownedIds)}
          {supportedIds.length > 0 &&
            renderFeatureList('Supports', 'supported', supportedIds)}
        </CollapsibleSection>
      );
    },

    // Structured children consumed by the <responsibility>
    // renderer above. Render nothing if they bubble up on their
    // own (schema drift — validator would reject, but defense in
    // depth).
    name: () => null,
    scope: () => null,
    'does-not-own': () => null,
    'failure-surface': () => null,
    owns: () => null,
    supports: () => null,
  };
}

function collectScopeItems(responsibility: XmlElement): string[] {
  const scope = findChild(responsibility, 'scope');
  if (!scope) return [];
  return findChildren(scope, 'item')
    .map((i) => textContent(i).trim())
    .filter((s): s is string => Boolean(s));
}

interface Deferral {
  scope: string;
  to: string;
}

function collectDeferrals(responsibility: XmlElement): Deferral[] {
  const block = findChild(responsibility, 'does-not-own');
  if (!block) return [];
  return findChildren(block, 'defers')
    .map((d) => ({
      scope: textContent(d).trim(),
      to: typeof d.attributes.to === 'string' ? d.attributes.to.trim() : '',
    }))
    .filter((d) => d.scope && d.to);
}

/**
 * Back-compat module-level export: a renderer map with no
 * feature-name resolution. Existing callers (tests, non-panel
 * usages) get bare feat IDs; the dashboard's ``RequirementsPanel``
 * opts into the factory form so its cards can show names.
 */
export const requirementsRenderers: XmlRendererMap = makeRequirementsRenderers();
