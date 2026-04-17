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
 * Four prose sections in fixed order. All four are opaque prose
 * blobs — the validator doesn't parse their contents, and the
 * renderer just outputs each as whitespace-preserving text.
 * Fenced code blocks are explicitly discouraged at generation
 * time; if the LLM emits them anyway they render as-is via the
 * whitespace-pre-wrap style.
 */
export const implRenderers: XmlRendererMap = {
  implementation: (node, ctx) => (
    <div className="not-prose space-y-6">{ctx.renderChildren(node.children)}</div>
  ),

  behavior: (node) => (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
        Behavior
      </h2>
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </section>
  ),

  invariants: (node) => (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
        Invariants
      </h2>
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </section>
  ),

  sequencing: (node) => (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
        Sequencing
      </h2>
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </section>
  ),

  'edge-cases': (node) => (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
        Edge Cases
      </h2>
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </section>
  ),
};
