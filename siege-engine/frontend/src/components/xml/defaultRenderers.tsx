import type { ReactNode } from 'react';
import type { XmlElement, XmlRenderContext } from './types';
import { findChild, textContent } from './types';

/**
 * Schema-agnostic fallback renderer.
 *
 * Used by ``XmlDocument`` whenever it encounters an element that
 * has no entry in the active renderer map. The behavior is
 * intentionally simple and document-ish:
 *
 * * Leaf text element (only text children) → ``<p>``. Empty
 *   leaves render nothing.
 * * Element whose first child is a ``<name>`` → rendered as a
 *   ``<section>`` with a heading derived from the name's text.
 *   Heading level is picked from ``ctx.depth`` so nested sections
 *   get progressively smaller headings, capped at ``<h6>``.
 * * Element with only nested elements → rendered as a ``<section>``
 *   wrapping the recursively rendered children.
 * * Elements with mixed children (text + elements) → rendered
 *   inline so interleaved prose survives.
 *
 * Schema-specific renderers can override any of this; this file
 * is the "what do we do if nobody claimed this tag" layer.
 */
export function renderUnknownElement(
  node: XmlElement,
  ctx: XmlRenderContext
): ReactNode {
  const children = node.children;
  if (children.length === 0) return null;

  // Leaf text — render as a paragraph.
  const onlyText = children.every((c) => c.type === 'text');
  if (onlyText) {
    const text = children
      .map((c) => (c.type === 'text' ? c.value : ''))
      .join('')
      .trim();
    if (!text) return null;
    return <p>{text}</p>;
  }

  // Section with a name child — consume the name as a heading and
  // render the remaining children below it.
  const nameChild = findChild(node, 'name');
  const otherChildren = nameChild
    ? children.filter((c) => c !== nameChild)
    : children;
  const heading = nameChild ? textContent(nameChild).trim() : null;
  const level = Math.min(2 + ctx.depth, 6);
  const Heading = `h${level}` as 'h2' | 'h3' | 'h4' | 'h5' | 'h6';

  return (
    <section>
      {heading && <Heading>{heading}</Heading>}
      {ctx.renderChildren(otherChildren)}
    </section>
  );
}
