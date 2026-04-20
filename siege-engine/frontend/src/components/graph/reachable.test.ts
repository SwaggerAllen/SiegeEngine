import { describe, expect, it } from 'vitest';
import type { ElementDefinition } from 'cytoscape';
import { reachableSets } from './reachable';

function n(id: string): ElementDefinition {
  return { data: { id } };
}
function e(id: string, source: string, target: string): ElementDefinition {
  return { data: { id, source, target } };
}

describe('reachableSets', () => {
  it('returns just the seed when the node is isolated', () => {
    const sets = reachableSets([n('a'), n('b')], 'a');
    expect([...sets.down]).toEqual(['a']);
    expect([...sets.up]).toEqual(['a']);
    expect(sets.downEdges.size).toBe(0);
    expect(sets.upEdges.size).toBe(0);
  });

  it('walks a linear chain downstream', () => {
    const els = [
      n('a'),
      n('b'),
      n('c'),
      e('ab', 'a', 'b'),
      e('bc', 'b', 'c'),
    ];
    const sets = reachableSets(els, 'a');
    expect([...sets.down].sort()).toEqual(['a', 'b', 'c']);
    expect([...sets.up]).toEqual(['a']);
    expect([...sets.downEdges].sort()).toEqual(['ab', 'bc']);
  });

  it('walks upstream from a sink', () => {
    const els = [
      n('a'),
      n('b'),
      n('c'),
      e('ab', 'a', 'b'),
      e('bc', 'b', 'c'),
    ];
    const sets = reachableSets(els, 'c');
    expect([...sets.up].sort()).toEqual(['a', 'b', 'c']);
    expect([...sets.down]).toEqual(['c']);
    expect([...sets.upEdges].sort()).toEqual(['ab', 'bc']);
  });

  it('handles branches without double-counting', () => {
    const els = [
      n('a'),
      n('b1'),
      n('b2'),
      n('c'),
      e('ab1', 'a', 'b1'),
      e('ab2', 'a', 'b2'),
      e('b1c', 'b1', 'c'),
      e('b2c', 'b2', 'c'),
    ];
    const sets = reachableSets(els, 'a');
    expect([...sets.down].sort()).toEqual(['a', 'b1', 'b2', 'c']);
    expect(sets.downEdges.size).toBe(4);
  });

  it('terminates on cycles', () => {
    const els = [
      n('a'),
      n('b'),
      e('ab', 'a', 'b'),
      e('ba', 'b', 'a'),
    ];
    const sets = reachableSets(els, 'a');
    expect([...sets.down].sort()).toEqual(['a', 'b']);
    expect([...sets.up].sort()).toEqual(['a', 'b']);
  });
});
