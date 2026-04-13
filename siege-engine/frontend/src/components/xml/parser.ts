import { XMLParser } from 'fast-xml-parser';
import type { XmlElement, XmlNode } from './types';

/**
 * Parse a raw XML string into our canonical XmlNode tree.
 *
 * Uses ``fast-xml-parser`` with ``preserveOrder: true`` so document
 * order of children is maintained, which matters for rendering
 * features/sections in the order the LLM emitted them.
 *
 * Throws on any parse failure or when no root element is found.
 * Callers should catch and render a fallback; the ``XmlDocument``
 * component does this automatically.
 */
export function parseXml(raw: string): XmlElement {
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
  // Find the first real element at the top level (skipping any
  // stray text nodes, XML declarations, or comments).
  for (const entry of tree) {
    const node = convertEntry(entry);
    if (node && node.type === 'element') {
      return node;
    }
  }
  throw new Error('No root element found in XML');
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
