import type { XmlRendererMap } from './types';
import { findChildText } from './types';

/**
 * Renderer overrides for the requirements schema:
 *
 *   <requirements>
 *     <responsibility>
 *       <name>Authentication</name>
 *       <intent>…</intent>
 *     </responsibility>
 *     …
 *   </requirements>
 *
 * Every responsibility becomes a bordered card with a name heading
 * and the paragraph-length intent. Shape is deliberately parallel
 * to ``featureRenderers`` — each bootstrap doc ships its own
 * schema map next to its component file; the ``XmlDocument``
 * walker and default renderers are shared.
 */
export const requirementsRenderers: XmlRendererMap = {
  requirements: (node, ctx) => (
    <div className="not-prose space-y-3">{ctx.renderChildren(node.children)}</div>
  ),

  responsibility: (node) => {
    const name = findChildText(node, 'name') ?? 'Untitled';
    const intent = findChildText(node, 'intent') ?? '';
    return (
      <article className="bg-gray-800/40 border border-gray-700 rounded p-4 space-y-1">
        <h3 className="font-semibold text-white m-0 text-sm">{name}</h3>
        {intent && <p className="text-sm text-gray-300 m-0">{intent}</p>}
      </article>
    );
  },

  // <name> and <intent> are consumed by the <responsibility>
  // renderer above. Render nothing if they bubble up on their own
  // (schema drift — the validator would reject it, but defense in
  // depth).
  name: () => null,
  intent: () => null,
};
