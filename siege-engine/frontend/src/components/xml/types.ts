import type { ReactNode } from 'react';

/**
 * Canonical XML tree shape used throughout the XML rendering
 * package. Deliberately parser-agnostic: the parser module
 * converts whatever third-party shape it gets into this tree so
 * renderers and helpers never have to know where the data came
 * from.
 *
 * The tree is intentionally simple — elements carry a name, a
 * flat attribute map, and an ordered children list. Mixed
 * content (text interleaved with elements) is preserved through
 * ``type: 'text'`` child nodes.
 */
export interface XmlElement {
  type: 'element';
  name: string;
  attributes: Record<string, string | true>;
  children: XmlNode[];
}

export interface XmlText {
  type: 'text';
  value: string;
}

export type XmlNode = XmlElement | XmlText;

/**
 * Context passed to every custom renderer. Renderers receive the
 * element they're handling plus this object, which lets them
 * recurse into children, render individual nodes, and know how
 * deep they are in the tree (for picking heading levels, etc.).
 */
export interface XmlRenderContext {
  /** Current depth in the tree. The root element is ``depth=0``. */
  depth: number;
  /** The active renderer map; exposed in case a renderer wants to
   * delegate to a peer renderer by name. */
  renderers: XmlRendererMap;
  /** Recursively render a list of child nodes. */
  renderChildren: (children: XmlNode[]) => ReactNode;
  /** Recursively render a single node. ``key`` is optional but
   * important when a renderer emits a dynamic list. */
  renderNode: (node: XmlNode, key?: string | number) => ReactNode;
}

/**
 * A renderer is a function that takes an element + context and
 * returns a React node. Renderers are fully in charge of their
 * children: they can ignore them, walk them with ``renderChildren``,
 * pull specific child values via helpers, or mix and match.
 */
export type XmlTagRenderer = (
  node: XmlElement,
  ctx: XmlRenderContext
) => ReactNode;

/**
 * Per-schema override map. Keys are lowercase tag names; values
 * are the renderers that handle them. Tags without an entry fall
 * through to the schema-agnostic default renderer.
 */
export type XmlRendererMap = Record<string, XmlTagRenderer>;

// ── Helpers that custom renderers commonly want ─────────────────────

/** Concatenate all descendant text of a node. */
export function textContent(node: XmlNode): string {
  if (node.type === 'text') return node.value;
  return node.children.map(textContent).join('');
}

/** Return the first child element with the given tag name, or undefined. */
export function findChild(node: XmlElement, tagName: string): XmlElement | undefined {
  return node.children.find(
    (c): c is XmlElement => c.type === 'element' && c.name === tagName
  );
}

/** Return **all** child elements with the given tag name, in order. */
export function findChildren(node: XmlElement, tagName: string): XmlElement[] {
  return node.children.filter(
    (c): c is XmlElement => c.type === 'element' && c.name === tagName
  );
}

/** Return the trimmed text content of the first child with the given
 * name, or ``undefined`` if no such child exists. */
export function findChildText(node: XmlElement, tagName: string): string | undefined {
  const child = findChild(node, tagName);
  return child ? textContent(child).trim() : undefined;
}

/** True iff the element has at least one direct child with the given name. */
export function hasChild(node: XmlElement, tagName: string): boolean {
  return findChild(node, tagName) !== undefined;
}
