import { CollapsibleSection } from './CollapsibleSection';
import type { XmlRendererMap } from './types';
import { textContent } from './types';

/**
 * Renderer overrides for the Phase 8 impl schema:
 *
 *   <implementation>
 *     <behavior>…</behavior>
 *     <invariants>…</invariants>
 *     <sequencing>…</sequencing>
 *     <edge-cases>…</edge-cases>
 *   </implementation>
 *
 * Four prose sections in fixed order. Each section renders as a
 * collapsed ``<CollapsibleSection>`` by default so the page opens
 * on a birds-eye view of the four section titles; callers expand
 * individual sections to read their prose bodies. Contents are
 * opaque prose — the validator doesn't parse them, and this
 * renderer just emits each as whitespace-preserving text.
 */
export const implRenderers: XmlRendererMap = {
  implementation: (node, ctx) => (
    <div className="not-prose space-y-3">{ctx.renderChildren(node.children)}</div>
  ),

  behavior: (node) => (
    <CollapsibleSection summary="Behavior">
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </CollapsibleSection>
  ),

  invariants: (node) => (
    <CollapsibleSection summary="Invariants">
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </CollapsibleSection>
  ),

  sequencing: (node) => (
    <CollapsibleSection summary="Sequencing">
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </CollapsibleSection>
  ),

  'edge-cases': (node) => (
    <CollapsibleSection summary="Edge Cases">
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </CollapsibleSection>
  ),
};
