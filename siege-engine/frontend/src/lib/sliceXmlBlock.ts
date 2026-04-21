/**
 * Extract a top-level ``<tag>...</tag>`` block from a raw XML
 * content blob. Used by the per-tier list/components tabs on the
 * feature expansion, requirements, and sysarch panels so users
 * can see the parsed structured list without scrolling past
 * ``<introduction>`` preambles or other sibling blocks.
 *
 * Non-greedy regex. Returns ``null`` when the tag isn't present
 * in the blob. Caller decides what to render in either case.
 */
export function sliceXmlBlock(
  blob: string | null | undefined,
  tag: string,
): string | null {
  const trimmed = (blob ?? '').trim();
  if (!trimmed) return null;
  const re = new RegExp(`<${tag}[\\s\\S]*?</${tag}>`, 'i');
  const match = re.exec(trimmed);
  return match ? match[0] : null;
}
