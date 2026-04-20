import { describe, expect, it } from 'vitest';
import type { StructureNode } from '../../api/structure';
import { SYNTHETIC_IDS } from './buildNavTree';
import { tabScope } from './tabScope';

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

describe('tabScope', () => {
  it('returns empty scope when nothing is selected', () => {
    expect(tabScope(null, null, [])).toEqual({
      tabs: [],
      activeKey: null,
      scopeLabel: null,
    });
  });

  it('returns empty scope for synthetic ids', () => {
    expect(tabScope(SYNTHETIC_IDS.VOCABULARY, null, []).tabs).toEqual([]);
    expect(tabScope(SYNTHETIC_IDS.DAG, null, []).tabs).toEqual([]);
  });

  it('gives system tabs when a system-tier node is selected', () => {
    const nodes = [
      n('exp_1', 'expansion', null),
      n('reqs_1', 'reqs', null),
      n('sys_1', 'sysarch', null),
    ];
    const scope = tabScope('reqs_1', null, nodes);
    expect(scope.scopeLabel).toBe('System');
    expect(scope.activeKey).toBe('reqs');
    expect(scope.tabs.map((t) => t.key)).toEqual(['expansion', 'reqs', 'sysarch']);
  });

  it('top-level comp: Overview default, all tabs when fanin + impl exist', () => {
    const nodes = [
      n('comp_1', 'comp', null, { name: 'Billing' }),
      n('subreqs_1', 'subreqs', 'comp_1'),
      n('fanin_1', 'fanin', 'comp_1'),
      n('impl_1', 'impl', 'comp_1'),
    ];
    const scope = tabScope('comp_1', null, nodes);
    expect(scope.scopeLabel).toBe('Billing');
    expect(scope.activeKey).toBe('overview');
    expect(scope.tabs.map((t) => t.key)).toEqual([
      'overview',
      'subreqs',
      'comparch',
      'fanin',
      'impl',
    ]);
  });

  it('top-level comp with ?view=comparch activates the comparch tab', () => {
    const nodes = [n('comp_1', 'comp', null, { name: 'Billing' })];
    const scope = tabScope('comp_1', 'comparch', nodes);
    expect(scope.activeKey).toBe('comparch');
  });

  it('child tiers of a top-level comp fall under that comp scope', () => {
    const nodes = [
      n('comp_1', 'comp', null, { name: 'Billing' }),
      n('subreqs_1', 'subreqs', 'comp_1'),
    ];
    const scope = tabScope('subreqs_1', null, nodes);
    expect(scope.scopeLabel).toBe('Billing');
    expect(scope.activeKey).toBe('subreqs');
    expect(scope.tabs.map((t) => t.key)).toContain('overview');
  });

  it('presentational comp hides the Fan-in tab (no fanin node)', () => {
    const nodes = [
      n('comp_1', 'comp', null, { name: 'UI', kind: 'presentational' }),
      n('subreqs_1', 'subreqs', 'comp_1'),
    ];
    const scope = tabScope('comp_1', null, nodes);
    expect(scope.tabs.map((t) => t.key)).not.toContain('fanin');
  });

  it('subcomponent scope: Subcomparch + Impl when impl exists', () => {
    const nodes = [
      n('comp_1', 'comp', null, { name: 'Billing' }),
      n('comp_sub', 'comp', 'comp_1', { name: 'TokenStore' }),
      n('impl_sub', 'impl', 'comp_sub'),
    ];
    const scope = tabScope('comp_sub', null, nodes);
    expect(scope.scopeLabel).toBe('TokenStore');
    expect(scope.activeKey).toBe('subcomparch');
    expect(scope.tabs.map((t) => t.key)).toEqual(['subcomparch', 'sub-impl']);
  });

  it('subcomponent impl selection activates sub-impl tab', () => {
    const nodes = [
      n('comp_1', 'comp', null),
      n('comp_sub', 'comp', 'comp_1'),
      n('impl_sub', 'impl', 'comp_sub'),
    ];
    const scope = tabScope('impl_sub', null, nodes);
    expect(scope.activeKey).toBe('sub-impl');
  });
});
