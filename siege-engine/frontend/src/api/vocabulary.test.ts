import { describe, it, expect } from 'vitest';
import { buildVocabEntryXml, parseVocabEntry } from './vocabulary';

describe('buildVocabEntryXml', () => {
  it('builds a definition-only entry', () => {
    const xml = buildVocabEntryXml('A test definition.', null, []);
    expect(xml).toContain('<vocab-entry>');
    expect(xml).toContain('<definition>A test definition.</definition>');
    expect(xml).not.toContain('<disambiguation>');
    expect(xml).not.toContain('<see-also>');
  });

  it('includes disambiguation when provided', () => {
    const xml = buildVocabEntryXml('Def.', 'Not the other thing.', []);
    expect(xml).toContain('<disambiguation>Not the other thing.</disambiguation>');
  });

  it('includes see-also refs when provided', () => {
    const xml = buildVocabEntryXml('Def.', null, ['leaf', 'fan-out']);
    expect(xml).toContain('<see-also>');
    expect(xml).toContain('<ref name="leaf"/>');
    expect(xml).toContain('<ref name="fan-out"/>');
  });

  it('omits disambiguation when empty string', () => {
    const xml = buildVocabEntryXml('Def.', '', []);
    expect(xml).not.toContain('<disambiguation>');
  });

  it('escapes XML special chars in definition', () => {
    const xml = buildVocabEntryXml(
      'Uses <brackets> & ampersands.',
      null,
      []
    );
    expect(xml).toContain('&lt;brackets&gt;');
    expect(xml).toContain('&amp;');
  });
});

describe('parseVocabEntry', () => {
  it('extracts definition', () => {
    const parsed = parseVocabEntry(
      '<vocab-entry><definition>Test def.</definition></vocab-entry>'
    );
    expect(parsed.definition).toBe('Test def.');
    expect(parsed.disambiguation).toBeNull();
    expect(parsed.seeAlsoNames).toEqual([]);
  });

  it('extracts all three sections', () => {
    const parsed = parseVocabEntry(
      '<vocab-entry>' +
        '<definition>Def.</definition>' +
        '<disambiguation>Not X.</disambiguation>' +
        '<see-also><ref name="a"/><ref name="b"/></see-also>' +
        '</vocab-entry>'
    );
    expect(parsed.definition).toBe('Def.');
    expect(parsed.disambiguation).toBe('Not X.');
    expect(parsed.seeAlsoNames).toEqual(['a', 'b']);
  });

  it('unescapes XML entities in definition', () => {
    const parsed = parseVocabEntry(
      '<vocab-entry><definition>Uses &lt;brackets&gt; &amp; stuff.</definition></vocab-entry>'
    );
    expect(parsed.definition).toBe('Uses <brackets> & stuff.');
  });

  it('falls back to raw content when definition tag missing', () => {
    // Shouldn't happen for server-validated content, but defensive.
    const parsed = parseVocabEntry('some raw text');
    expect(parsed.definition).toBe('some raw text');
    expect(parsed.disambiguation).toBeNull();
  });
});

describe('buildVocabEntryXml + parseVocabEntry round-trip', () => {
  it('round-trips definition + disambiguation + see-also', () => {
    const xml = buildVocabEntryXml(
      'Round-trip definition text.',
      'Not the other thing.',
      ['alpha', 'beta']
    );
    const parsed = parseVocabEntry(xml);
    expect(parsed.definition).toBe('Round-trip definition text.');
    expect(parsed.disambiguation).toBe('Not the other thing.');
    expect(parsed.seeAlsoNames).toEqual(['alpha', 'beta']);
  });
});
