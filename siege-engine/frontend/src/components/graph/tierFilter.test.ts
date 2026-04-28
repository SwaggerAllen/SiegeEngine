import { describe, expect, it } from 'vitest';
import type { ElementDefinition } from 'cytoscape';
import {
  availableGroups,
  expandToTypes,
  parseHiddenParam,
  serializeHiddenParam,
  type TierGroupKey,
} from './tierFilter';

function el(id: string, type: string): ElementDefinition {
  return { data: { id, type, name: id } };
}

describe('parseHiddenParam', () => {
  it('returns an empty set for null / empty input', () => {
    expect(parseHiddenParam(null).size).toBe(0);
    expect(parseHiddenParam('').size).toBe(0);
  });

  it('parses a comma-separated list of known group keys', () => {
    const set = parseHiddenParam('features,implementations');
    expect(set.has('features')).toBe(true);
    expect(set.has('implementations')).toBe(true);
    expect(set.size).toBe(2);
  });

  it('silently drops unknown keys (forward-compat for renames)', () => {
    const set = parseHiddenParam('features,bogus,fanin');
    expect(set.has('features')).toBe(true);
    expect(set.has('fanin')).toBe(true);
    expect(set.size).toBe(2);
  });
});

describe('serializeHiddenParam', () => {
  it('returns null for an empty set', () => {
    expect(serializeHiddenParam(new Set())).toBeNull();
  });

  it('serializes in the canonical (chip-row) order', () => {
    // Insertion order shouldn't matter — output order should match
    // the chip-row order so the URL is stable across toggles.
    const reversed = new Set<TierGroupKey>([
      'implementations',
      'features',
      'fanin',
    ]);
    expect(serializeHiddenParam(reversed)).toBe('features,fanin,implementations');
  });
});

describe('availableGroups', () => {
  it('returns only groups that have at least one matching node', () => {
    const elements: ElementDefinition[] = [
      el('feat_1', 'feat'),
      el('comp_1', 'comp-top'),
    ];
    const groups = availableGroups(elements);
    const keys = groups.map((g) => g.key);
    expect(keys).toEqual(['features', 'components']);
  });

  it('groups types from different views under one chip (feat + external-feat)', () => {
    const elements: ElementDefinition[] = [
      el('feat_1', 'external-feat'),
      el('comp_sub', 'comp-sub'),
    ];
    const groups = availableGroups(elements);
    expect(groups.map((g) => g.key)).toEqual(['features', 'subcomponents']);
  });

  it('returns the chip-row order regardless of element order', () => {
    const elements: ElementDefinition[] = [
      el('impl_1', 'impl'),
      el('feat_1', 'feat'),
      el('resp_1', 'resp-top'),
    ];
    const keys = availableGroups(elements).map((g) => g.key);
    expect(keys).toEqual(['features', 'responsibilities', 'implementations']);
  });
});

describe('expandToTypes', () => {
  it('expands a group key into its node-type set', () => {
    const types = expandToTypes(new Set<TierGroupKey>(['features']));
    expect(types.has('feat')).toBe(true);
    expect(types.has('external-feat')).toBe(true);
    expect(types.size).toBe(2);
  });

  it('combines multiple group keys', () => {
    const types = expandToTypes(
      new Set<TierGroupKey>(['features', 'implementations']),
    );
    expect(types.has('feat')).toBe(true);
    expect(types.has('external-feat')).toBe(true);
    expect(types.has('impl')).toBe(true);
    expect(types.size).toBe(3);
  });

  it('returns an empty set for an empty input', () => {
    expect(expandToTypes(new Set()).size).toBe(0);
  });
});
