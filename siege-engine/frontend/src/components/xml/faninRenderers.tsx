import { CollapsibleSection } from './CollapsibleSection';
import type { XmlRendererMap } from './types';
import { textContent } from './types';

/**
 * Renderer overrides for the Phase 7 fan-in schema:
 *
 *   <fanin>
 *     <summary>…</summary>
 *     <exposed-surface>…</exposed-surface>
 *     <realized-behavior>…</realized-behavior>
 *   </fanin>
 *
 * Three prose sections in fixed order. The <summary> section
 * defaults to expanded because it's the first thing a debugger
 * wants to see; the two longer sections collapse so the page
 * opens as an at-a-glance view. Contents are opaque prose — the
 * validator doesn't parse them, and this renderer just emits
 * each as whitespace-preserving text.
 */
export const faninRenderers: XmlRendererMap = {
  fanin: (node, ctx) => (
    <div className="not-prose space-y-3">{ctx.renderChildren(node.children)}</div>
  ),

  summary: (node) => (
    <CollapsibleSection summary="Summary" defaultOpen>
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </CollapsibleSection>
  ),

  'exposed-surface': (node) => (
    <CollapsibleSection summary="Exposed Surface (as built)">
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </CollapsibleSection>
  ),

  'realized-behavior': (node) => (
    <CollapsibleSection summary="Realized Behavior (as built)">
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </CollapsibleSection>
  ),
};
