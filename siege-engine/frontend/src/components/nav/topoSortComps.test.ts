import { describe, expect, it } from 'vitest';
import type { StructureEdge, StructureNode } from '../../api/structure';
import { topoSortComps } from './topoSortComps';

function comp(
  id: string,
  display_order: number,
  overrides: Partial<StructureNode> = {},
): StructureNode {
  return {
    id,
    tier: 'comp',
    kind: 'domain',
    parent_id: null,
    name: id,
    display_order,
    content: '',
    has_content: false,
    has_pending_draft: false,
    generation_running: false,
    has_error: false,
    needs_user_action: false,
    is_stale: false,
    staleness_reasons: [],
    techspec: '',
    pubapi: '',
    is_deferred: false,
    ...overrides,
  };
}

function dep(source: string, target: string): StructureEdge {
  return { id: `${source}->${target}`, edge_type: 'dependency', source_id: source, target_id: target };
}

describe('topoSortComps', () => {
  it('returns input order when there are no edges', () => {
    const nodes = [comp('comp_a', 1), comp('comp_b', 0), comp('comp_c', 2)];
    const sorted = topoSortComps(nodes, []);
    // No edges → tiebreak on display_order.
    expect(sorted.map((c) => c.id)).toEqual(['comp_b', 'comp_a', 'comp_c']);
  });

  it('places dependencies before their dependents', () => {
    const nodes = [comp('app', 0), comp('auth', 1), comp('db', 2)];
    // app -> auth -> db (app depends on auth depends on db)
    const edges = [dep('app', 'auth'), dep('auth', 'db')];
    const sorted = topoSortComps(nodes, edges);
    expect(sorted.map((c) => c.id)).toEqual(['db', 'auth', 'app']);
  });

  it('promotes is_foundation comps within a frontier tie', () => {
    const nodes = [
      comp('app', 0),
      comp('foundation', 1, { is_foundation: true } as Partial<StructureNode>),
      comp('utils', 2),
    ];
    // app depends on both foundation and utils, but foundation and
    // utils are independent. Foundation should sort first within
    // the frontier despite higher display_order than app.
    const edges = [dep('app', 'foundation'), dep('app', 'utils')];
    const sorted = topoSortComps(nodes, edges);
    expect(sorted.map((c) => c.id)).toEqual(['foundation', 'utils', 'app']);
  });

  it('handles diamond dependencies', () => {
    // bottom <- left <- top, bottom <- right <- top
    const nodes = [
      comp('top', 0),
      comp('left', 1),
      comp('right', 2),
      comp('bottom', 3),
    ];
    const edges = [
      dep('top', 'left'),
      dep('top', 'right'),
      dep('left', 'bottom'),
      dep('right', 'bottom'),
    ];
    const sorted = topoSortComps(nodes, edges).map((c) => c.id);
    // bottom must be before left + right; left + right must be
    // before top.
    expect(sorted[0]).toBe('bottom');
    expect(sorted[3]).toBe('top');
    expect(sorted.slice(1, 3).sort()).toEqual(['left', 'right']);
  });

  it('ignores non-dependency edges', () => {
    const nodes = [comp('a', 0), comp('b', 1)];
    const edges: StructureEdge[] = [
      { id: 'e1', edge_type: 'domain_parent', source_id: 'b', target_id: 'a' },
    ];
    const sorted = topoSortComps(nodes, edges).map((c) => c.id);
    // Only display_order tiebreak — domain_parent doesn't reorder.
    expect(sorted).toEqual(['a', 'b']);
  });

  it('appends cycle-stranded nodes in display order', () => {
    // Cycle a -> b -> a; both have outgoing-deps == 1 forever.
    const nodes = [comp('c', 2), comp('a', 0), comp('b', 1)];
    const edges = [dep('a', 'b'), dep('b', 'a')];
    const sorted = topoSortComps(nodes, edges).map((c) => c.id);
    // c has no edges → comes first; a + b stranded → appended in
    // input/display order.
    expect(sorted).toEqual(['c', 'a', 'b']);
  });
});
