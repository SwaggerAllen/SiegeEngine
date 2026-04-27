import { describe, it, expect } from 'vitest';
import { parseXml, parseXmlAll } from './parser';

describe('parseXml', () => {
  it('parses a simple element into the canonical tree', () => {
    const root = parseXml('<features><feature><name>A</name></feature></features>');
    expect(root.type).toBe('element');
    expect(root.name).toBe('features');
    expect(root.children).toHaveLength(1);
    const feature = root.children[0];
    if (feature.type !== 'element') throw new Error('expected element');
    expect(feature.name).toBe('feature');
    expect(feature.children).toHaveLength(1);
    const nameEl = feature.children[0];
    if (nameEl.type !== 'element') throw new Error('expected element');
    expect(nameEl.name).toBe('name');
    // Text node under <name>
    expect(nameEl.children).toHaveLength(1);
    expect(nameEl.children[0].type).toBe('text');
    if (nameEl.children[0].type === 'text') {
      expect(nameEl.children[0].value).toBe('A');
    }
  });

  it('preserves sibling order', () => {
    const root = parseXml(
      '<r><a>1</a><b>2</b><c>3</c></r>'
    );
    expect(root.children.map((c) => (c.type === 'element' ? c.name : '#text'))).toEqual([
      'a',
      'b',
      'c',
    ]);
  });

  it('captures attributes without the @_ prefix', () => {
    const root = parseXml('<feature priority="high" flag><name>X</name></feature>');
    expect(root.attributes.priority).toBe('high');
    expect(root.attributes.flag).toBe(true);
  });

  it('handles an empty self-closing element', () => {
    const root = parseXml('<feature><name>X</name><implicit/></feature>');
    if (root.type !== 'element') throw new Error('expected element');
    const implicit = root.children.find(
      (c) => c.type === 'element' && c.name === 'implicit'
    );
    expect(implicit).toBeTruthy();
    if (implicit?.type !== 'element') throw new Error('expected element');
    expect(implicit.children).toEqual([]);
  });

  it('throws on empty input', () => {
    expect(() => parseXml('')).toThrow();
  });

  it('throws when there is no root element', () => {
    expect(() => parseXml('just plain text, no tags')).toThrow();
  });

  it('returns the first root when the document has multiple top-level elements', () => {
    // Sysarch et al. emit ``<introduction>...</introduction><sysarch>...</sysarch>``;
    // single-root callers historically saw only the introduction. Behaviour
    // preserved for backward compat — multi-root callers use parseXmlAll.
    const root = parseXml(
      '<introduction>preamble</introduction><sysarch><techspec>t</techspec></sysarch>',
    );
    expect(root.name).toBe('introduction');
  });
});

describe('parseXmlAll', () => {
  it('returns every top-level element in document order', () => {
    const roots = parseXmlAll(
      '<introduction>preamble</introduction><sysarch><techspec>t</techspec></sysarch>',
    );
    expect(roots).toHaveLength(2);
    expect(roots[0].name).toBe('introduction');
    expect(roots[1].name).toBe('sysarch');
  });

  it('returns a single element for normal one-root documents', () => {
    const roots = parseXmlAll('<features><feature><name>A</name></feature></features>');
    expect(roots).toHaveLength(1);
    expect(roots[0].name).toBe('features');
  });

  it('skips text nodes and comments between roots', () => {
    const roots = parseXmlAll(
      '<introduction>x</introduction>\n<!-- comment -->\n<sysarch/>',
    );
    expect(roots.map((r) => r.name)).toEqual(['introduction', 'sysarch']);
  });

  it('returns an empty array when no element is found', () => {
    expect(parseXmlAll('plain text')).toEqual([]);
  });
});
