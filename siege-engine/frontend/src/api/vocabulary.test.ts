import { describe, it, expect } from 'vitest';
import { parseVocabEntry } from './vocabulary';

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
