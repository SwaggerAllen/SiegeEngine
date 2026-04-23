import type { XmlElement, XmlRendererMap } from './types';
import { findChild, findChildText, findChildren } from './types';
import { ResponsibilityCard } from './ResponsibilityCard';

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
 * Each atom renders via :component:`ResponsibilityCard` — a
 * one-line card with the name on the left and a collapsed-by-
 * default feat-tag disclosure on the right. Feature IDs resolve
 * to ``name (feat_xxxxxxxx)`` when the caller supplies a feature
 * name map; otherwise the raw id appears.
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
        <ResponsibilityCard
          name={name}
          feats={feats}
          featureNames={featureNames}
        />
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
