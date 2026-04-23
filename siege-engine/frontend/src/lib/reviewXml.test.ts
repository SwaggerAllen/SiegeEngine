import { describe, expect, it } from 'vitest';
import {
  diagnoseReview,
  formatSelectedAsFeedback,
  parseReview,
} from './reviewXml';

const VALID_INTRO_SCORE =
  '<intro>Overall shape is right with a couple of gaps.</intro>' +
  '<score>68</score>';

describe('parseReview', () => {
  it('parses two-section review with findings', () => {
    const raw =
      '<review>' +
      VALID_INTRO_SCORE +
      '<handles-structure>' +
      '<finding id="h1">Feature names overlap.</finding>' +
      '<finding id="h2">Intent is restated name.</finding>' +
      '</handles-structure>' +
      '<architectural-decisions>' +
      '<finding id="a1">Decomp axis split.</finding>' +
      '</architectural-decisions>' +
      '</review>';
    const parsed = parseReview(raw);
    expect(parsed).not.toBeNull();
    expect(parsed!.intro).toContain('Overall shape');
    expect(parsed!.score).toBe(68);
    expect(parsed!.handlesStructure.map((f) => f.id)).toEqual(['h1', 'h2']);
    expect(parsed!.architecturalDecisions.map((f) => f.id)).toEqual(['a1']);
    expect(parsed!.handlesStructure[0].text).toBe('Feature names overlap.');
  });

  it('accepts empty sections with a high score', () => {
    const raw =
      '<review>' +
      '<intro>Clean.</intro>' +
      '<score>95</score>' +
      '<handles-structure></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    const parsed = parseReview(raw);
    expect(parsed).not.toBeNull();
    expect(parsed!.score).toBe(95);
    expect(parsed!.handlesStructure).toEqual([]);
    expect(parsed!.architecturalDecisions).toEqual([]);
  });

  it('returns null for missing review root', () => {
    expect(parseReview('<handles-structure></handles-structure>')).toBeNull();
  });

  it('returns null when intro is missing', () => {
    const raw =
      '<review>' +
      '<score>70</score>' +
      '<handles-structure></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(parseReview(raw)).toBeNull();
  });

  it('returns null when intro is empty', () => {
    const raw =
      '<review>' +
      '<intro>  </intro>' +
      '<score>70</score>' +
      '<handles-structure></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(parseReview(raw)).toBeNull();
  });

  it('returns null when score is missing', () => {
    const raw =
      '<review>' +
      '<intro>ok.</intro>' +
      '<handles-structure></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(parseReview(raw)).toBeNull();
  });

  it('returns null when score is non-numeric', () => {
    const raw =
      '<review>' +
      '<intro>ok.</intro>' +
      '<score>A+</score>' +
      '<handles-structure></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(parseReview(raw)).toBeNull();
  });

  it('returns null when score is out of range', () => {
    const raw =
      '<review>' +
      '<intro>ok.</intro>' +
      '<score>150</score>' +
      '<handles-structure></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(parseReview(raw)).toBeNull();
  });

  it('returns null for missing required sections', () => {
    const raw =
      '<review>' +
      VALID_INTRO_SCORE +
      '<handles-structure></handles-structure>' +
      '</review>';
    expect(parseReview(raw)).toBeNull();
  });

  it('returns null when a finding is missing its id', () => {
    const raw =
      '<review>' +
      VALID_INTRO_SCORE +
      '<handles-structure><finding>no id</finding></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(parseReview(raw)).toBeNull();
  });

  it('returns null on duplicate finding ids', () => {
    const raw =
      '<review>' +
      VALID_INTRO_SCORE +
      '<handles-structure><finding id="h1">A</finding></handles-structure>' +
      '<architectural-decisions><finding id="h1">B</finding></architectural-decisions>' +
      '</review>';
    expect(parseReview(raw)).toBeNull();
  });

  it('returns null for empty input', () => {
    expect(parseReview('')).toBeNull();
    expect(parseReview('   ')).toBeNull();
  });

  it('returns null for pre-Phase-8 markdown content', () => {
    expect(parseReview('## Handles & structure\n- foo')).toBeNull();
  });
});

describe('formatSelectedAsFeedback', () => {
  const review = {
    intro: 'Stub intro.',
    score: 60,
    handlesStructure: [
      { id: 'h1', text: 'Names overlap.' },
      { id: 'h2', text: 'Restated intent.' },
    ],
    architecturalDecisions: [{ id: 'a1', text: 'Wrong axis.' }],
  };

  it('groups by section and bullets each finding', () => {
    const out = formatSelectedAsFeedback(review, new Set(['h1', 'a1']));
    expect(out).toContain('Handles & structure:');
    expect(out).toContain('- Names overlap.');
    expect(out).toContain('Architectural decisions:');
    expect(out).toContain('- Wrong axis.');
    expect(out).not.toContain('Restated intent');
  });

  it('does not leak intro or score into feedback', () => {
    const out = formatSelectedAsFeedback(review, new Set(['h1']));
    expect(out).not.toContain('Stub intro');
    expect(out).not.toContain('60');
  });

  it('omits sections with no selected findings', () => {
    const out = formatSelectedAsFeedback(review, new Set(['a1']));
    expect(out).not.toContain('Handles & structure');
    expect(out).toContain('Architectural decisions');
  });

  it('returns empty string when nothing selected', () => {
    expect(formatSelectedAsFeedback(review, new Set())).toBe('');
  });
});

describe('parseReview — tag names inside finding bodies', () => {
  it('parses reviews that reference XML tag names inline', () => {
    // Real-world case: the reviewer writes prose like
    // "three `<covers>` entries" inside a finding body. DOMParser
    // would normally read that as an unclosed ``<covers>`` tag
    // and fail the whole review. The pre-processor escapes stray
    // angle brackets inside every finding body.
    const raw =
      '<review>' +
      VALID_INTRO_SCORE +
      '<handles-structure>' +
      '<finding id="h1">Bundle intent overlaps with Provisioning scope.</finding>' +
      '<finding id="h2">feat_XYZ has three `<covers>` entries for one feature — ambiguous owner.</finding>' +
      '</handles-structure>' +
      '<architectural-decisions>' +
      '<finding id="a1">Workspace <foo>aggregation</foo> is too fine-grained.</finding>' +
      '</architectural-decisions>' +
      '</review>';
    const parsed = parseReview(raw);
    expect(parsed).not.toBeNull();
    expect(parsed!.handlesStructure).toHaveLength(2);
    expect(parsed!.architecturalDecisions).toHaveLength(1);
    // Escaped tag names survive as literal angle brackets in the
    // finding text so the reviewer's intent is still readable.
    expect(parsed!.handlesStructure[1].text).toContain('<covers>');
    expect(parsed!.architecturalDecisions[0].text).toContain('<foo>');
  });
});

describe('diagnoseReview', () => {
  const valid =
    '<review>' +
    VALID_INTRO_SCORE +
    '<handles-structure><finding id="h1">body.</finding></handles-structure>' +
    '<architectural-decisions><finding id="a1">body.</finding></architectural-decisions>' +
    '</review>';

  it('reports ok on a clean parse', () => {
    const d = diagnoseReview(valid);
    expect(d.status).toBe('ok');
    expect(d.hasReviewTag).toBe(true);
    expect(d.hasIntroSection).toBe(true);
    expect(d.hasScoreSection).toBe(true);
    expect(d.hasHandlesSection).toBe(true);
    expect(d.hasArchSection).toBe(true);
    expect(d.findingCount).toBe(2);
  });

  it('reports empty on empty input', () => {
    expect(diagnoseReview('').status).toBe('empty');
    expect(diagnoseReview('   ').status).toBe('empty');
  });

  it('reports missing_review_root when <review> is absent', () => {
    const d = diagnoseReview(
      '<handles-structure><finding id="h1">x</finding></handles-structure>' +
        '<architectural-decisions></architectural-decisions>',
    );
    expect(d.status).toBe('missing_review_root');
    expect(d.hasReviewTag).toBe(false);
  });

  it('reports missing_intro when that section is absent', () => {
    const raw =
      '<review>' +
      '<score>70</score>' +
      '<handles-structure></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    const d = diagnoseReview(raw);
    expect(d.status).toBe('missing_intro');
    expect(d.hasIntroSection).toBe(false);
  });

  it('reports empty_intro when intro is present but blank', () => {
    const raw =
      '<review>' +
      '<intro>  </intro>' +
      '<score>70</score>' +
      '<handles-structure></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(diagnoseReview(raw).status).toBe('empty_intro');
  });

  it('reports missing_score when that section is absent', () => {
    const raw =
      '<review>' +
      '<intro>ok.</intro>' +
      '<handles-structure></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(diagnoseReview(raw).status).toBe('missing_score');
  });

  it('reports invalid_score for out-of-range values', () => {
    const raw =
      '<review>' +
      '<intro>ok.</intro>' +
      '<score>150</score>' +
      '<handles-structure></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(diagnoseReview(raw).status).toBe('invalid_score');
  });

  it('reports missing_handles_structure when that section is absent', () => {
    const raw =
      '<review>' +
      VALID_INTRO_SCORE +
      '<architectural-decisions><finding id="a1">x</finding></architectural-decisions>' +
      '</review>';
    const d = diagnoseReview(raw);
    expect(d.status).toBe('missing_handles_structure');
    expect(d.hasReviewTag).toBe(true);
    expect(d.hasArchSection).toBe(true);
  });

  it('reports missing_architectural_decisions when that section is absent', () => {
    const raw =
      '<review>' +
      VALID_INTRO_SCORE +
      '<handles-structure><finding id="h1">x</finding></handles-structure>' +
      '</review>';
    expect(diagnoseReview(raw).status).toBe(
      'missing_architectural_decisions',
    );
  });

  it('reports finding_missing_id when an id attribute is blank', () => {
    const raw =
      '<review>' +
      VALID_INTRO_SCORE +
      '<handles-structure><finding>no id here</finding></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(diagnoseReview(raw).status).toBe('finding_missing_id');
  });

  it('reports finding_empty_body when body text is empty', () => {
    const raw =
      '<review>' +
      VALID_INTRO_SCORE +
      '<handles-structure><finding id="h1"></finding></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(diagnoseReview(raw).status).toBe('finding_empty_body');
  });

  it('reports duplicate_finding_id when two findings share an id', () => {
    const raw =
      '<review>' +
      VALID_INTRO_SCORE +
      '<handles-structure><finding id="x">a</finding></handles-structure>' +
      '<architectural-decisions><finding id="x">b</finding></architectural-decisions>' +
      '</review>';
    expect(diagnoseReview(raw).status).toBe('duplicate_finding_id');
  });

  it('includes a preview of the raw text', () => {
    const raw = 'some preamble ' + valid;
    const d = diagnoseReview(raw);
    expect(d.preview).toContain('some preamble');
    expect(d.preview.length).toBeLessThanOrEqual(400);
  });
});
