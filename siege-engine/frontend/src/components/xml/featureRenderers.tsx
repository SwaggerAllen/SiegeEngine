import type { XmlRendererMap } from './types';
import { findChildText, findChildren, hasChild } from './types';

/**
 * Renderer overrides for the feature-expansion schema:
 *
 *   <features>
 *     [<group><name>…</name> <feature>…</feature>…</group>]
 *     [<feature>
 *        <name>…</name>
 *        <intent>…</intent>
 *        [<implicit/>]
 *      </feature>]
 *   </features>
 *
 * Each ``<feature>`` becomes a bordered card with a name heading,
 * an optional "inferred" badge, and the paragraph-length intent.
 * Groups become section headers with their feature children laid
 * out below. Ungrouped features render next to grouped ones
 * naturally because ``<features>`` just walks its children.
 *
 * When Phase 3 reqs/sysarch land they ship their own renderer
 * map alongside a sibling file — this file is the template for
 * those. Helpers are in ``./types`` and the ``<XmlDocument>``
 * walker is shared.
 */
export const featureRenderers: XmlRendererMap = {
  features: (node, ctx) => (
    <div className="not-prose space-y-6">{ctx.renderChildren(node.children)}</div>
  ),

  group: (node, ctx) => {
    const name = findChildText(node, 'name') ?? 'Group';
    const features = findChildren(node, 'feature');
    return (
      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
          {name}
          <span className="ml-2 text-gray-600 font-normal normal-case tracking-normal">
            ({features.length})
          </span>
        </h2>
        <div className="space-y-3">
          {features.map((f, i) => ctx.renderNode(f, i))}
        </div>
      </section>
    );
  },

  feature: (node) => {
    const name = findChildText(node, 'name') ?? 'Untitled';
    const intent = findChildText(node, 'intent') ?? '';
    const implicit = hasChild(node, 'implicit');
    return (
      <article className="bg-gray-800/40 border border-gray-700 rounded p-4 space-y-1">
        <div className="flex items-baseline gap-2">
          <h3 className="font-semibold text-white m-0 text-sm">{name}</h3>
          {implicit && (
            <span
              className="text-xs font-normal italic text-blue-300/80"
              title="Inferred by the LLM — not explicit in the input doc"
            >
              inferred
            </span>
          )}
        </div>
        {intent && <p className="text-sm text-gray-300 m-0">{intent}</p>}
      </article>
    );
  },

  // The <name>, <intent>, and <implicit/> children are consumed by
  // their parent renderer above. If they ever bubble up to the
  // walker on their own (e.g. because a schema drift lets one
  // appear outside a <feature>), render nothing rather than
  // surface raw tag text.
  name: () => null,
  intent: () => null,
  implicit: () => null,
};
