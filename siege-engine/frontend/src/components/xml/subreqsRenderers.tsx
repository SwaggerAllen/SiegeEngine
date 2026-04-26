import type { XmlElement, XmlRendererMap } from './types';
import { findChild, findChildren } from './types';
import { SubresponsibilityCard } from './SubresponsibilityCard';

/**
 * Renderer overrides for the atomic subrequirements grammar:
 *
 *   <subrequirements>
 *     <subresponsibility>
 *       <name>Card Tokenization</name>
 *       <feats>
 *         <feat id="feat_payment01"/>
 *       </feats>
 *       <derived-from>
 *         <resp id="resp_payment01"/>
 *       </derived-from>
 *     </subresponsibility>
 *   </subrequirements>
 *
 * Each atom renders via :component:`SubresponsibilityCard` — name
 * on the left, two collapsible count pills (feats + parent resps)
 * on the right. Feature IDs resolve to ``name (feat_xxxxxxxx)``
 * when the caller supplies a feature name map; otherwise the raw
 * id appears.
 */
export function makeSubreqsRenderers(
  featureNames: Record<string, string> = {},
): XmlRendererMap {
  return {
    subrequirements: (node, ctx) => (
      <div className="not-prose space-y-2">
        {ctx.renderChildren(node.children)}
      </div>
    ),

    subresponsibility: (node) => {
      const name = findChildText(node, 'name') ?? 'Untitled';
      const feats = collectFeatIds(node);
      const parentIds = collectDerivedFromIds(node);
      return (
        <SubresponsibilityCard
          name={name}
          feats={feats}
          parentIds={parentIds}
          featureNames={featureNames}
        />
      );
    },

    // Structured children consumed by the <subresponsibility>
    // renderer above. Render nothing if they bubble up on their
    // own (schema drift — validator would reject).
    name: () => null,
    feats: () => null,
    feat: () => null,
    'derived-from': () => null,
    resp: () => null,
  };
}

function findChildText(element: XmlElement, name: string): string | null {
  const child = findChild(element, name);
  if (!child) return null;
  const parts: string[] = [];
  for (const c of child.children) {
    if (c.type === 'text') parts.push(c.value);
  }
  const joined = parts.join('').trim();
  return joined || null;
}

function collectFeatIds(subresp: XmlElement): string[] {
  const block = findChild(subresp, 'feats');
  if (!block) return [];
  return findChildren(block, 'feat')
    .map((f) => (typeof f.attributes.id === 'string' ? f.attributes.id : null))
    .filter((id): id is string => id !== null);
}

function collectDerivedFromIds(subresp: XmlElement): string[] {
  const block = findChild(subresp, 'derived-from');
  if (!block) return [];
  return findChildren(block, 'resp')
    .map((r) => (typeof r.attributes.id === 'string' ? r.attributes.id : null))
    .filter((id): id is string => id !== null);
}

/**
 * Back-compat module-level export with no feature-name resolution.
 * Existing callers (tests, non-panel usages) get bare feat IDs;
 * the dashboard's ``SubreqsPanel`` opts into the factory form so
 * its cards can show names.
 */
export const subreqsRenderers: XmlRendererMap = makeSubreqsRenderers();
