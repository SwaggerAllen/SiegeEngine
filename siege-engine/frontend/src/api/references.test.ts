import { describe, expect, it } from 'vitest';
import { buildReferenceXml, parseReference } from './references';

describe('buildReferenceXml', () => {
  it('builds a minimal title + body reference', () => {
    const xml = buildReferenceXml('My Runbook', 'Deploy steps go here.');
    expect(xml).toContain('<reference>');
    expect(xml).toContain('<title>My Runbook</title>');
    expect(xml).toContain('<body>Deploy steps go here.</body>');
    expect(xml).not.toContain('<see-also>');
  });

  it('includes see-also refs when provided', () => {
    const xml = buildReferenceXml('Title', 'Body.', ['ref_ABCDEFGH', 'ref_JKMNPQRS']);
    expect(xml).toContain('<see-also>');
    expect(xml).toContain('<ref to="ref_ABCDEFGH"/>');
    expect(xml).toContain('<ref to="ref_JKMNPQRS"/>');
  });

  it('escapes XML-sensitive characters in title and body', () => {
    const xml = buildReferenceXml('A & B', '<script>evil()</script>');
    expect(xml).toContain('<title>A &amp; B</title>');
    expect(xml).toContain('<body>&lt;script&gt;evil()&lt;/script&gt;</body>');
  });
});

describe('parseReference', () => {
  it('extracts title and body from a valid reference', () => {
    const raw =
      '<reference><title>Run</title><body>Body text.</body></reference>';
    const parsed = parseReference(raw);
    expect(parsed.title).toBe('Run');
    expect(parsed.body).toBe('Body text.');
    expect(parsed.seeAlsoIds).toEqual([]);
  });

  it('extracts see-also ids', () => {
    const raw =
      '<reference><title>T</title><body>B</body>' +
      '<see-also><ref to="ref_ABCDEFGH"/><ref to="ref_JKMNPQRS"/></see-also>' +
      '</reference>';
    const parsed = parseReference(raw);
    expect(parsed.seeAlsoIds).toEqual(['ref_ABCDEFGH', 'ref_JKMNPQRS']);
  });

  it('round-trips through build + parse', () => {
    const xml = buildReferenceXml('T', 'B', ['ref_ABCDEFGH']);
    const parsed = parseReference(xml);
    expect(parsed.title).toBe('T');
    expect(parsed.body).toBe('B');
    expect(parsed.seeAlsoIds).toEqual(['ref_ABCDEFGH']);
  });

  it('unescapes XML entities', () => {
    const xml = buildReferenceXml('A & B', 'X < Y');
    const parsed = parseReference(xml);
    expect(parsed.title).toBe('A & B');
    expect(parsed.body).toBe('X < Y');
  });
});
