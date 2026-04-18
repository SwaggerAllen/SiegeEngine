// Frontend parser + apply-formatter for the Phase 8 AI review
// XML format. Mirrors ``backend/graph/parsers/review_xml.py``;
// keep in sync if the schema changes.
//
// The parser is lenient on the outer wrapper (preamble /
// postamble is fine) but strict on the inner structure:
// both ``<handles-structure>`` and ``<architectural-decisions>``
// must be present, every ``<finding>`` needs a non-empty ``id``
// and body. Malformed reviews return ``null`` — the caller
// falls back to the raw-markdown render for pre-Phase-8 content
// or any review that slipped through backend validation.

export interface ReviewFinding {
  id: string;
  text: string;
}

export interface ParsedReview {
  handlesStructure: ReviewFinding[];
  architecturalDecisions: ReviewFinding[];
}

const HANDLES_SECTION = 'handles-structure';
const ARCH_SECTION = 'architectural-decisions';

/**
 * Parse a review XML string into structured sections. Returns
 * ``null`` for anything that doesn't match the schema so
 * callers can fall back to raw rendering.
 *
 * The browser's DOMParser can parse XML directly — no external
 * deps needed. We extract the first ``<review>`` element found
 * anywhere in the input (tolerant of preamble/postamble), then
 * walk its two required sections.
 */
export function parseReview(raw: string): ParsedReview | null {
  if (!raw?.trim()) return null;

  const trimmed = raw.trim();
  // DOMParser's XML mode treats preamble prose as a parse error,
  // so wrap the input in a synthetic root that swallows
  // whitespace/prose outside the actual ``<review>`` tag.
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(
      `<root>${trimmed}</root>`,
      'application/xml',
    );
  } catch {
    return null;
  }
  if (doc.querySelector('parsererror')) return null;

  const reviewEl = doc.querySelector('review');
  if (!reviewEl) return null;

  const handles = reviewEl.querySelector(HANDLES_SECTION);
  const arch = reviewEl.querySelector(ARCH_SECTION);
  if (!handles || !arch) return null;

  const handlesFindings = extractFindings(handles);
  const archFindings = extractFindings(arch);
  if (handlesFindings === null || archFindings === null) return null;

  const ids = new Set<string>();
  for (const f of [...handlesFindings, ...archFindings]) {
    if (ids.has(f.id)) return null;
    ids.add(f.id);
  }

  return {
    handlesStructure: handlesFindings,
    architecturalDecisions: archFindings,
  };
}

function extractFindings(section: Element): ReviewFinding[] | null {
  const findings: ReviewFinding[] = [];
  // Only immediate-child ``<finding>`` elements; defensive
  // against accidental nesting if the LLM produces something
  // weird.
  for (const el of Array.from(section.children)) {
    if (el.tagName.toLowerCase() !== 'finding') continue;
    const id = (el.getAttribute('id') ?? '').trim();
    const text = (el.textContent ?? '').trim();
    if (!id || !text) return null;
    findings.push({ id, text });
  }
  return findings;
}

/**
 * Format a subset of findings back into a feedback prompt the
 * generator's feedback endpoint can consume. Groups findings
 * by section so the LLM sees which axis each concern came from.
 */
export function formatSelectedAsFeedback(
  review: ParsedReview,
  selectedIds: ReadonlySet<string>,
): string {
  const lines: string[] = [];
  const handles = review.handlesStructure.filter((f) => selectedIds.has(f.id));
  const arch = review.architecturalDecisions.filter((f) => selectedIds.has(f.id));
  if (handles.length > 0) {
    lines.push('Handles & structure:');
    for (const f of handles) {
      lines.push(`- ${f.text}`);
    }
    lines.push('');
  }
  if (arch.length > 0) {
    lines.push('Architectural decisions:');
    for (const f of arch) {
      lines.push(`- ${f.text}`);
    }
    lines.push('');
  }
  return lines.join('\n').trim();
}
