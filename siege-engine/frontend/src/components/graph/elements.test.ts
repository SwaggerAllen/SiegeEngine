import { describe, expect, it } from 'vitest';
import type { StructureEdge, StructureNode } from '../../api/structure';
import {
  drillElements,
  externalContextFor,
  topLevelElements,
} from './elements';

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

function e(
  id: string,
  edge_type: StructureEdge['edge_type'],
  source_id: string,
  target_id: string,
): StructureEdge {
  return { id, edge_type, source_id, target_id };
}

function ids(elements: ReturnType<typeof topLevelElements>): string[] {
  return elements
    .filter((el) => {
      const d = el.data as { source?: string; target?: string };
      return d.source === undefined && d.target === undefined;
    })
    .map((el) => (el.data as { id?: string }).id)
    .filter((id): id is string => id !== undefined);
}

function edgeIds(elements: ReturnType<typeof topLevelElements>): string[] {
  return elements
    .filter((el) => {
      const d = el.data as { source?: string; target?: string };
      return d.source !== undefined && d.target !== undefined;
    })
    .map((el) => (el.data as { id?: string }).id)
    .filter((id): id is string => id !== undefined);
}

describe('topLevelElements', () => {
  it('keeps features, top-level resps, top-level policies, top-level comps', () => {
    const elements = topLevelElements(
      [
        n('feat_F1', 'feat', null),
        n('resp_R1', 'resp', null),
        n('resp_R2', 'resp', 'comp_C1'), // subresp, excluded
        n('policy_P1', 'policy', null),
        n('policy_P2', 'policy', 'comp_C1'), // local policy, excluded
        n('comp_C1', 'comp', null),
        n('comp_C2', 'comp', 'comp_C1'), // subcomp, excluded
        n('fanin_FN1', 'fanin', 'comp_C1'), // excluded
        n('impl_I1', 'impl', 'comp_C1'), // excluded
      ],
      [],
    );
    expect(ids(elements).sort()).toEqual([
      'comp_C1',
      'feat_F1',
      'policy_P1',
      'resp_R1',
    ]);
  });

  it('keeps edges only when both endpoints survive the filter', () => {
    const elements = topLevelElements(
      [
        n('feat_F1', 'feat', null),
        n('resp_R1', 'resp', null),
        n('comp_C1', 'comp', null),
        n('resp_R2', 'resp', 'comp_C1'), // subresp
      ],
      [
        e('edge_1', 'decomposition', 'feat_F1', 'resp_R1'), // kept
        e('edge_2', 'decomposition', 'resp_R1', 'comp_C1'), // kept
        e('edge_3', 'decomposition', 'resp_R2', 'comp_C1'), // dropped (subresp excluded)
      ],
    );
    expect(edgeIds(elements).sort()).toEqual(['edge_1', 'edge_2']);
  });

  it('flips source and target for dependency + domain_parent edges', () => {
    const elements = topLevelElements(
      [n('comp_C1', 'comp', null), n('comp_C2', 'comp', null)],
      [
        e('edge_dep', 'dependency', 'comp_C1', 'comp_C2'),
        e('edge_dom', 'domain_parent', 'comp_C1', 'comp_C2'),
        e('edge_decomp', 'decomposition', 'comp_C1', 'comp_C2'),
      ],
    );
    const byId: Record<
      string,
      { source?: string; target?: string }
    > = {};
    for (const el of elements) {
      const d = el.data as { id?: string; source?: string; target?: string };
      if (d.id && d.source) byId[d.id] = { source: d.source, target: d.target };
    }
    expect(byId.edge_dep).toEqual({ source: 'comp_C2', target: 'comp_C1' });
    expect(byId.edge_dom).toEqual({ source: 'comp_C2', target: 'comp_C1' });
    expect(byId.edge_decomp).toEqual({
      source: 'comp_C1',
      target: 'comp_C2',
    });
  });

  it('sets isStale attribute on stale nodes', () => {
    const elements = topLevelElements(
      [n('comp_C1', 'comp', null, { is_stale: true })],
      [],
    );
    const data = elements[0].data as { isStale?: string };
    expect(data.isStale).toBe('1');
  });
});

describe('externalContextFor', () => {
  it('walks back to top-level resps and features via decomposition', () => {
    const nodes = [
      n('feat_F1', 'feat', null),
      n('resp_R1', 'resp', null),
      n('comp_C1', 'comp', null),
    ];
    const edges = [
      e('edge_1', 'decomposition', 'feat_F1', 'resp_R1'),
      e('edge_2', 'decomposition', 'resp_R1', 'comp_C1'),
    ];
    const context = externalContextFor('comp_C1', nodes, edges);
    expect(context.map((n) => n.id).sort()).toEqual(['feat_F1', 'resp_R1']);
  });

  it('includes top-level policies applied to the drilled comp', () => {
    const nodes = [
      n('policy_P1', 'policy', null),
      n('comp_C1', 'comp', null),
    ];
    const edges = [e('edge_1', 'policy_application', 'policy_P1', 'comp_C1')];
    const context = externalContextFor('comp_C1', nodes, edges);
    expect(context.map((n) => n.id)).toEqual(['policy_P1']);
  });

  it('skips subresps and component-local policies', () => {
    const nodes = [
      n('resp_R1', 'resp', 'comp_C0'), // subresp
      n('policy_P1', 'policy', 'comp_C0'), // local policy
      n('comp_C1', 'comp', null),
    ];
    const edges = [
      e('edge_1', 'decomposition', 'resp_R1', 'comp_C1'),
      e('edge_2', 'policy_application', 'policy_P1', 'comp_C1'),
    ];
    expect(externalContextFor('comp_C1', nodes, edges)).toEqual([]);
  });
});

describe('drillElements', () => {
  const drilledId = 'comp_C1';

  it('includes subresps / subcomps / fanin / local policies', () => {
    const elements = drillElements(
      drilledId,
      [
        n(drilledId, 'comp', null),
        n('resp_subR', 'resp', drilledId),
        n('comp_sub1', 'comp', drilledId),
        n('fanin_FN', 'fanin', drilledId),
        n('policy_local', 'policy', drilledId),
        n('comp_unrelated', 'comp', null), // not under drilled
      ],
      [],
    );
    expect(ids(elements).sort()).toEqual([
      'comp_C1',
      'comp_sub1',
      'fanin_FN',
      'policy_local',
      'resp_subR',
    ]);
  });

  it('hides impls by default, reveals when subcomp id is in the set', () => {
    const nodes = [
      n(drilledId, 'comp', null),
      n('comp_sub1', 'comp', drilledId),
      n('impl_I1', 'impl', 'comp_sub1'),
    ];
    const hidden = drillElements(drilledId, nodes, []);
    expect(ids(hidden)).not.toContain('impl_I1');

    const revealed = drillElements(
      drilledId,
      nodes,
      [],
      new Set(['comp_sub1']),
    );
    expect(ids(revealed)).toContain('impl_I1');
  });

  it('adds external-context layer for feats/resps/policies tracing in', () => {
    const elements = drillElements(
      drilledId,
      [
        n('feat_F1', 'feat', null),
        n('resp_R1', 'resp', null),
        n('policy_P1', 'policy', null),
        n(drilledId, 'comp', null),
      ],
      [
        e('edge_1', 'decomposition', 'feat_F1', 'resp_R1'),
        e('edge_2', 'decomposition', 'resp_R1', drilledId),
        e('edge_3', 'policy_application', 'policy_P1', drilledId),
      ],
    );
    expect(ids(elements).sort()).toEqual([
      drilledId,
      'feat_F1',
      'policy_P1',
      'resp_R1',
    ]);
  });
});
