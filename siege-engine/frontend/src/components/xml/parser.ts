import { XMLParser } from 'fast-xml-parser';
import type { XmlElement, XmlNode } from './types';

/**
 * Parse a raw XML string into our canonical XmlNode tree.
 *
 * Uses ``fast-xml-parser`` with ``preserveOrder: true`` so document
 * order of children is maintained, which matters for rendering
 * features/sections in the order the LLM emitted them.
 *
 * Returns the first top-level element. Use :func:`parseXmlAll` if
 * the document has multiple top-level elements (e.g. the bootstrap
 * tiers that emit ``<introduction>`` alongside their main block —
 * sysarch, requirements, expansion). ``parseXml`` is kept for
 * call sites that genuinely want a single root.
 *
 * Throws on any parse failure or when no root element is found.
 * Callers should catch and render a fallback; the ``XmlDocument``
 * component does this automatically.
 */
export function parseXml(raw: string): XmlElement {
  const roots = parseXmlAll(raw);
  if (roots.length === 0) {
    throw new Error('No root element found in XML');
  }
  return roots[0];
}

/**
 * Parse a raw XML string into all top-level elements in document
 * order. Skips text nodes, XML declarations, and comments.
 *
 * The bootstrap tiers (expansion, requirements, sysarch) emit two
 * top-level blocks: an ``<introduction>`` preamble plus the main
 * tier output (``<features>``, ``<requirements>``, ``<sysarch>``).
 * Tiers below the top three emit a single root, in which case this
 * returns a one-element array.
 *
 * Throws on parse failure. Returns ``[]`` if the document parses
 * but contains no element nodes.
 */
export function parseXmlAll(raw: string): XmlElement[] {
  const parser = new XMLParser({
    preserveOrder: true,
    ignoreAttributes: false,
    allowBooleanAttributes: true,
    attributeNamePrefix: '',
    trimValues: false,
  });
  const tree = parser.parse(raw);
  if (!Array.isArray(tree)) {
    throw new Error('fast-xml-parser returned a non-array top-level tree');
  }
  const roots: XmlElement[] = [];
  for (const entry of tree) {
    const node = convertEntry(entry);
    if (node && node.type === 'element') {
      roots.push(node);
    }
  }
  return roots;
}

/** Convert one ``preserveOrder`` entry into our XmlNode shape.
 *
 * Each entry is an object like ``{ tagName: [childEntries], ':@': attrs }``
 * or ``{ '#text': 'value' }``. Text entries become XmlText nodes;
 * anything else becomes an XmlElement. Unknown special keys
 * (declarations, comments, etc.) are dropped — we don't render them.
 */
function convertEntry(entry: unknown): XmlNode | null {
  if (typeof entry !== 'object' || entry === null) return null;
  const obj = entry as Record<string, unknown>;
  const attributesRaw = (obj[':@'] as Record<string, string | true> | undefined) ?? {};

  for (const key of Object.keys(obj)) {
    if (key === ':@') continue;
    const value = obj[key];
    if (key === '#text') {
      return { type: 'text', value: String(value) };
    }
    // Skip declaration / comment / CDATA nodes — they carry keys
    // like ``?xml``, ``#comment``, ``#cdata`` in this parser. We
    // render the content around them but not the nodes themselves.
    if (key.startsWith('?') || key.startsWith('#')) return null;

    const rawChildren = Array.isArray(value) ? value : [];
    const children: XmlNode[] = [];
    for (const childEntry of rawChildren) {
      const child = convertEntry(childEntry);
      if (child) children.push(child);
    }
    return {
      type: 'element',
      name: key,
      attributes: attributesRaw,
      children,
    };
  }
  return null;
}
