import type { XmlRendererMap } from './types';
import { findChildren, textContent } from './types';

/**
 * Renderer overrides for the Phase 6.6 reference schema:
 *
 *   <reference>
 *     <title>…</title>
 *     <body>…opaque markdown / prose…</body>
 *     [<see-also>
 *        <ref to="ref_..."/>…
 *      </see-also>]
 *   </reference>
 *
 * ``<body>`` is opaque — the validator doesn't parse its content,
 * so the renderer just outputs its text verbatim inside a
 * whitespace-preserving block. If authors want markdown rendering
 * on top, that's a post-MVP follow-up.
 */
export const referencesRenderers: XmlRendererMap = {
  reference: (node, ctx) => (
    <article className="not-prose space-y-4">{ctx.renderChildren(node.children)}</article>
  ),

  title: (node) => (
    <h2 className="text-base font-bold text-white m-0">
      {textContent(node).trim() || 'Untitled'}
    </h2>
  ),

  body: (node) => (
    <pre className="whitespace-pre-wrap text-sm text-gray-200 bg-gray-800/40 border border-gray-700 rounded p-3 m-0 font-sans">
      {textContent(node).trim()}
    </pre>
  ),

  'see-also': (node) => {
    const refs = findChildren(node, 'ref');
    if (refs.length === 0) return null;
    return (
      <section className="text-sm">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0 mb-1">
          See also
        </h3>
        <ul className="list-disc pl-5 space-y-0.5 text-gray-300">
          {refs.map((r, i) => (
            <li key={i} className="font-mono text-xs text-blue-300">
              {r.attributes.to ?? ''}
            </li>
          ))}
        </ul>
      </section>
    );
  },

  ref: () => null,
};
