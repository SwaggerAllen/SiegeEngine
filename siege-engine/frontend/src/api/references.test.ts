import { describe, expect, it } from 'vitest';
import { parseReference } from './references';

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

  it('unescapes XML entities', () => {
    const raw =
      '<reference><title>A &amp; B</title><body>X &lt; Y</body></reference>';
    const parsed = parseReference(raw);
    expect(parsed.title).toBe('A & B');
    expect(parsed.body).toBe('X < Y');
  });
});
