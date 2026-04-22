import { describe, expect, it } from 'vitest';
import {
  diagnoseReview,
  formatSelectedAsFeedback,
  parseReview,
} from './reviewXml';

describe('parseReview', () => {
  it('parses two-section review with findings', () => {
    const raw =
      '<review>' +
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
    expect(parsed!.handlesStructure.map((f) => f.id)).toEqual(['h1', 'h2']);
    expect(parsed!.architecturalDecisions.map((f) => f.id)).toEqual(['a1']);
    expect(parsed!.handlesStructure[0].text).toBe('Feature names overlap.');
  });

  it('accepts empty sections', () => {
    const raw =
      '<review>' +
      '<handles-structure></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    const parsed = parseReview(raw);
    expect(parsed).not.toBeNull();
    expect(parsed!.handlesStructure).toEqual([]);
    expect(parsed!.architecturalDecisions).toEqual([]);
  });

  it('returns null for missing review root', () => {
    expect(parseReview('<handles-structure></handles-structure>')).toBeNull();
  });

  it('returns null for missing required sections', () => {
    const raw = '<review><handles-structure></handles-structure></review>';
    expect(parseReview(raw)).toBeNull();
  });

  it('returns null when a finding is missing its id', () => {
    const raw =
      '<review>' +
      '<handles-structure><finding>no id</finding></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(parseReview(raw)).toBeNull();
  });

  it('returns null on duplicate finding ids', () => {
    const raw =
      '<review>' +
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

  it('omits sections with no selected findings', () => {
    const out = formatSelectedAsFeedback(review, new Set(['a1']));
    expect(out).not.toContain('Handles & structure');
    expect(out).toContain('Architectural decisions');
  });

  it('returns empty string when nothing selected', () => {
    expect(formatSelectedAsFeedback(review, new Set())).toBe('');
  });
});

describe('diagnoseReview', () => {
  const valid =
    '<review>' +
    '<handles-structure><finding id="h1">body.</finding></handles-structure>' +
    '<architectural-decisions><finding id="a1">body.</finding></architectural-decisions>' +
    '</review>';

  it('reports ok on a clean parse', () => {
    const d = diagnoseReview(valid);
    expect(d.status).toBe('ok');
    expect(d.hasReviewTag).toBe(true);
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

  it('reports missing_handles_structure when that section is absent', () => {
    const raw =
      '<review>' +
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
      '<handles-structure><finding id="h1">x</finding></handles-structure>' +
      '</review>';
    expect(diagnoseReview(raw).status).toBe(
      'missing_architectural_decisions',
    );
  });

  it('reports finding_missing_id when an id attribute is blank', () => {
    const raw =
      '<review>' +
      '<handles-structure><finding>no id here</finding></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(diagnoseReview(raw).status).toBe('finding_missing_id');
  });

  it('reports finding_empty_body when body text is empty', () => {
    const raw =
      '<review>' +
      '<handles-structure><finding id="h1"></finding></handles-structure>' +
      '<architectural-decisions></architectural-decisions>' +
      '</review>';
    expect(diagnoseReview(raw).status).toBe('finding_empty_body');
  });

  it('reports duplicate_finding_id when two findings share an id', () => {
    const raw =
      '<review>' +
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
