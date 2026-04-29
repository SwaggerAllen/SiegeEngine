// Frontend parser + apply-formatter for the Phase 8 AI review
// XML format. Mirrors ``backend/graph/parsers/review_xml.py``;
// keep in sync if the schema changes.
//
// The parser is lenient on the outer wrapper (preamble /
// postamble is fine) but strict on the inner structure:
// ``<intro>``, ``<score>``, ``<handles-structure>``, and
// ``<architectural-decisions>`` must all be present; the score
// must parse as an integer 0-100; every ``<finding>`` needs a
// non-empty ``id`` and body. Malformed reviews return ``null``
// — the caller falls back to the raw-markdown render for
// pre-Phase-8 content or any review that slipped through
// backend validation.

export interface ReviewFinding {
  id: string;
  text: string;
}

export interface ParsedReview {
  intro: string;
  score: number;
  handlesStructure: ReviewFinding[];
  architecturalDecisions: ReviewFinding[];
}

const INTRO_SECTION = 'intro';
const SCORE_SECTION = 'score';
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

  const trimmed = escapeProseElements(raw.trim());
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

  const introEl = reviewEl.querySelector(INTRO_SECTION);
  const scoreEl = reviewEl.querySelector(SCORE_SECTION);
  const handles = reviewEl.querySelector(HANDLES_SECTION);
  const arch = reviewEl.querySelector(ARCH_SECTION);
  if (!introEl || !scoreEl || !handles || !arch) return null;

  const intro = (introEl.textContent ?? '').trim();
  if (!intro) return null;

  const scoreText = (scoreEl.textContent ?? '').trim();
  if (!scoreText) return null;
  const score = Number(scoreText);
  if (!Number.isInteger(score) || score < 0 || score > 100) return null;

  const handlesFindings = extractFindings(handles);
  const archFindings = extractFindings(arch);
  if (handlesFindings === null || archFindings === null) return null;

  const ids = new Set<string>();
  for (const f of [...handlesFindings, ...archFindings]) {
    if (ids.has(f.id)) return null;
    ids.add(f.id);
  }

  return {
    intro,
    score,
    handlesStructure: handlesFindings,
    architecturalDecisions: archFindings,
  };
}

/**
 * Escape stray angle brackets inside the review's prose-leaf
 * elements (``<intro>``, ``<score>``, ``<finding>``) before the
 * text hits ``DOMParser``.
 *
 * Reviewers routinely reference XML tag names in prose —
 * ``"three <covers> entries"``, ``"the <name> child"``,
 * ``"the `<subcomponents>` section is empty"`` — and the strict
 * XML parser then reads the inline tag name as an open tag and
 * fails the whole review with an "Opening and ending tag
 * mismatch" error. This was originally limited to ``<finding>``
 * bodies, but the same pattern shows up inside ``<intro>`` (the
 * one-paragraph summary frequently calls out missing or empty
 * sections by their tag name) — so we apply the same escape pass
 * to every prose-leaf element. ``<score>`` is included
 * defensively; in practice it's just an integer.
 *
 * Since these elements are pure prose (no nested markup ever
 * rendered), escaping ``<`` and ``>`` between their open/close
 * tags is safe and lossless for display.
 *
 * The wrapper element opens — ``<review>``, ``<handles-structure>``,
 * ``<architectural-decisions>`` — are left intact so the
 * structural parse still works.
 */
function escapeProseElements(raw: string): string {
  const proseTags = ['intro', 'score', 'finding'];
  let out = raw;
  for (const tag of proseTags) {
    const re = new RegExp(`(<${tag}\\b[^>]*>)([\\s\\S]*?)(</${tag}>)`, 'g');
    out = out.replace(re, (_match, open: string, body: string, close: string) => {
      const escaped = body.replace(/</g, '&lt;').replace(/>/g, '&gt;');
      return `${open}${escaped}${close}`;
    });
  }
  return out;
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

// ── Diagnostic helper ────────────────────────────────────────────────

export type ReviewDiagnosticStatus =
  | 'ok'
  | 'empty'
  | 'xml_parse_error'
  | 'missing_review_root'
  | 'missing_intro'
  | 'empty_intro'
  | 'missing_score'
  | 'invalid_score'
  | 'missing_handles_structure'
  | 'missing_architectural_decisions'
  | 'finding_missing_id'
  | 'finding_empty_body'
  | 'duplicate_finding_id';

export interface ReviewDiagnostic {
  status: ReviewDiagnosticStatus;
  detail: string;
  rawLength: number;
  hasReviewTag: boolean;
  hasIntroSection: boolean;
  hasScoreSection: boolean;
  hasHandlesSection: boolean;
  hasArchSection: boolean;
  findingCount: number;
  /** First ~400 chars of the raw text, whitespace-collapsed. */
  preview: string;
}

/**
 * Run the same rule set as :func:`parseReview` but surface the
 * specific failure reason + presence checks for each required tag.
 *
 * Used by the in-app "Why isn't this parsed?" affordance on the
 * Review tab when the raw fallback render kicks in — lets mobile
 * users screenshot a precise diagnosis without having to open
 * DevTools or copy the full review text.
 */
export function diagnoseReview(raw: string): ReviewDiagnostic {
  const trimmed = (raw ?? '').trim();
  const base = {
    rawLength: trimmed.length,
    hasReviewTag: false,
    hasIntroSection: false,
    hasScoreSection: false,
    hasHandlesSection: false,
    hasArchSection: false,
    findingCount: 0,
    preview: trimmed.replace(/\s+/g, ' ').slice(0, 400),
  };
  if (!trimmed) {
    return { ...base, status: 'empty', detail: 'Review text is empty.' };
  }

  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(
      `<root>${escapeProseElements(trimmed)}</root>`,
      'application/xml',
    );
  } catch (exc) {
    return {
      ...base,
      status: 'xml_parse_error',
      detail: `DOMParser threw: ${String(exc)}`,
    };
  }
  const parserError = doc.querySelector('parsererror');
  if (parserError) {
    return {
      ...base,
      status: 'xml_parse_error',
      detail:
        `DOMParser flagged a parsererror: ` +
        (parserError.textContent ?? '').trim().slice(0, 200),
    };
  }

  const reviewEl = doc.querySelector('review');
  const hasReviewTag = reviewEl !== null;
  const introEl = reviewEl?.querySelector(INTRO_SECTION) ?? null;
  const scoreEl = reviewEl?.querySelector(SCORE_SECTION) ?? null;
  const handles = reviewEl?.querySelector(HANDLES_SECTION) ?? null;
  const arch = reviewEl?.querySelector(ARCH_SECTION) ?? null;
  const findings = reviewEl?.querySelectorAll('finding') ?? { length: 0 };
  const presence = {
    ...base,
    hasReviewTag,
    hasIntroSection: introEl !== null,
    hasScoreSection: scoreEl !== null,
    hasHandlesSection: handles !== null,
    hasArchSection: arch !== null,
    findingCount: findings.length,
  };

  if (!hasReviewTag) {
    return {
      ...presence,
      status: 'missing_review_root',
      detail: 'No <review> element found anywhere in the raw text.',
    };
  }
  if (!introEl) {
    return {
      ...presence,
      status: 'missing_intro',
      detail: '<review> is missing the required <intro> section.',
    };
  }
  if (!(introEl.textContent ?? '').trim()) {
    return {
      ...presence,
      status: 'empty_intro',
      detail: '<intro> is present but its body is empty.',
    };
  }
  if (!scoreEl) {
    return {
      ...presence,
      status: 'missing_score',
      detail: '<review> is missing the required <score> section.',
    };
  }
  const scoreText = (scoreEl.textContent ?? '').trim();
  const scoreValue = Number(scoreText);
  if (!Number.isInteger(scoreValue) || scoreValue < 0 || scoreValue > 100) {
    return {
      ...presence,
      status: 'invalid_score',
      detail: `<score> must be an integer 0-100, got ${JSON.stringify(scoreText)}.`,
    };
  }
  if (!handles) {
    return {
      ...presence,
      status: 'missing_handles_structure',
      detail: '<review> is missing the required <handles-structure> section.',
    };
  }
  if (!arch) {
    return {
      ...presence,
      status: 'missing_architectural_decisions',
      detail:
        '<review> is missing the required <architectural-decisions> section.',
    };
  }

  const ids = new Set<string>();
  for (const section of [handles, arch]) {
    for (const el of Array.from(section.children)) {
      if (el.tagName.toLowerCase() !== 'finding') continue;
      const id = (el.getAttribute('id') ?? '').trim();
      const text = (el.textContent ?? '').trim();
      if (!id) {
        return {
          ...presence,
          status: 'finding_missing_id',
          detail:
            `A <finding> in <${section.tagName.toLowerCase()}> is missing its id= attribute. ` +
            `First 80 chars: ${el.outerHTML.slice(0, 80)}`,
        };
      }
      if (!text) {
        return {
          ...presence,
          status: 'finding_empty_body',
          detail: `<finding id="${id}"> has an empty body.`,
        };
      }
      if (ids.has(id)) {
        return {
          ...presence,
          status: 'duplicate_finding_id',
          detail: `Two <finding> entries share id="${id}".`,
        };
      }
      ids.add(id);
    }
  }

  return {
    ...presence,
    status: 'ok',
    detail: `Review parsed cleanly — ${ids.size} finding(s).`,
  };
}
