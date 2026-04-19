import { describe, expect, it } from 'vitest';
import type { StructureNode } from '../../api/structure';
import {
  ancestorIds,
  buildNavTree,
  defaultExpandedIds,
  SYNTHETIC_IDS,
} from './buildNavTree';

function n(
  id: string,
  tier: string,
  parent_id: string | null,
  overrides: Partial<StructureNode> = {},
): StructureNode {
  return {
    id,
    tier,
    kind: 'domain',
    parent_id,
    name: id,
    display_order: 0,
    content: '',
    has_content: true,
    has_pending_draft: false,
    generation_running: false,
    has_error: false,
    needs_user_action: false,
    is_stale: false,
    staleness_reasons: [],
    techspec: '',
    pubapi: '',
    ...overrides,
  };
}

describe('buildNavTree', () => {
  it('returns only synthetic entries when nodes are empty', () => {
    const items = buildNavTree([]);
    const ids = items.map((i) => i.id);
    expect(ids).toEqual([
      SYNTHETIC_IDS.VOCABULARY,
      SYNTHETIC_IDS.REFERENCES,
      SYNTHETIC_IDS.DECOMPOSITION_GRAPH,
    ]);
  });

  it('places singleton tiers above synthetic entries', () => {
    const items = buildNavTree([
      n('expansion_1', 'expansion', null),
      n('reqs_1', 'reqs', null),
      n('sysarch_1', 'sysarch', null),
    ]);
    const ids = items.map((i) => i.id);
    expect(ids).toEqual([
      'expansion_1',
      'reqs_1',
      'sysarch_1',
      SYNTHETIC_IDS.VOCABULARY,
      SYNTHETIC_IDS.REFERENCES,
      SYNTHETIC_IDS.DECOMPOSITION_GRAPH,
    ]);
  });

  it('nests subreqs + fan-in + subcomps under their owning comp', () => {
    const items = buildNavTree([
      n('comp_A', 'comp', null, { name: 'Billing' }),
      n('subreqs_A', 'subreqs', 'comp_A'),
      n('fanin_A', 'fanin', 'comp_A'),
      n('comp_Asub', 'comp', 'comp_A', { name: 'BillingStore' }),
      n('impl_Asub', 'impl', 'comp_Asub'),
    ]);
    const componentsRoot = items.find((i) => i.id === SYNTHETIC_IDS.COMPONENTS_ROOT);
    expect(componentsRoot).toBeDefined();
    const comp = componentsRoot!.children[0];
    expect(comp.id).toBe('comp_A');
    expect(comp.children.map((c) => c.id)).toEqual([
      'subreqs_A',
      'fanin_A',
      'comp_Asub',
    ]);
    const sub = comp.children.find((c) => c.id === 'comp_Asub')!;
    expect(sub.children.map((c) => c.id)).toEqual(['impl_Asub']);
  });

  it('places implementation directly under un-fanned-out comps', () => {
    const items = buildNavTree([
      n('comp_solo', 'comp', null, { name: 'Solo' }),
      n('impl_solo', 'impl', 'comp_solo'),
    ]);
    const comp = items
      .find((i) => i.id === SYNTHETIC_IDS.COMPONENTS_ROOT)!
      .children.find((c) => c.id === 'comp_solo')!;
    expect(comp.children.map((c) => c.id)).toEqual(['impl_solo']);
    expect(comp.children[0].role).toBe('component-impl');
  });

  it('orders top-level comps by display_order', () => {
    const items = buildNavTree([
      n('comp_C', 'comp', null, { display_order: 2 }),
      n('comp_A', 'comp', null, { display_order: 0 }),
      n('comp_B', 'comp', null, { display_order: 1 }),
    ]);
    const root = items.find((i) => i.id === SYNTHETIC_IDS.COMPONENTS_ROOT)!;
    expect(root.children.map((c) => c.id)).toEqual(['comp_A', 'comp_B', 'comp_C']);
  });

  it('skips the components root when no top-level comps exist', () => {
    const items = buildNavTree([n('expansion_1', 'expansion', null)]);
    expect(items.find((i) => i.id === SYNTHETIC_IDS.COMPONENTS_ROOT)).toBeUndefined();
  });

  it('rolls up descendant-pending and descendant-running flags', () => {
    const items = buildNavTree([
      n('comp_A', 'comp', null),
      n('comp_Asub', 'comp', 'comp_A'),
      n('impl_Asub', 'impl', 'comp_Asub', { has_pending_draft: true }),
    ]);
    const componentsRoot = items.find((i) => i.id === SYNTHETIC_IDS.COMPONENTS_ROOT)!;
    const comp = componentsRoot.children[0];
    const sub = comp.children[0];
    expect(sub.status.descendant_has_pending_draft).toBe(true);
    expect(comp.status.descendant_has_pending_draft).toBe(true);
    expect(componentsRoot.status.descendant_has_pending_draft).toBe(true);
    // Self flag on the impl leaf is also set
    expect(sub.children[0].status.has_pending_draft).toBe(true);
  });

  it('rolls up generation_running flag across the subtree', () => {
    const items = buildNavTree([
      n('comp_A', 'comp', null),
      n('fanin_A', 'fanin', 'comp_A', { generation_running: true }),
    ]);
    const componentsRoot = items.find((i) => i.id === SYNTHETIC_IDS.COMPONENTS_ROOT)!;
    const comp = componentsRoot.children[0];
    expect(comp.status.descendant_generation_running).toBe(true);
    expect(componentsRoot.status.descendant_generation_running).toBe(true);
  });
});

describe('ancestorIds', () => {
  it('returns every id on the path except the selected leaf', () => {
    const items = buildNavTree([
      n('comp_A', 'comp', null),
      n('comp_Asub', 'comp', 'comp_A'),
      n('impl_Asub', 'impl', 'comp_Asub'),
    ]);
    const ancestors = ancestorIds(items, 'impl_Asub');
    expect(ancestors.has(SYNTHETIC_IDS.COMPONENTS_ROOT)).toBe(true);
    expect(ancestors.has('comp_A')).toBe(true);
    expect(ancestors.has('comp_Asub')).toBe(true);
    expect(ancestors.has('impl_Asub')).toBe(false);
  });

  it('returns empty for an unknown id', () => {
    const items = buildNavTree([n('comp_A', 'comp', null)]);
    expect(ancestorIds(items, 'comp_NONE').size).toBe(0);
  });

  it('returns empty for null', () => {
    const items = buildNavTree([n('comp_A', 'comp', null)]);
    expect(ancestorIds(items, null).size).toBe(0);
  });
});

describe('defaultExpandedIds', () => {
  it('opens the components root by default', () => {
    expect(defaultExpandedIds().has(SYNTHETIC_IDS.COMPONENTS_ROOT)).toBe(true);
  });
});
