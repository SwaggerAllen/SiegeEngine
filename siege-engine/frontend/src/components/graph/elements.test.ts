import { describe, expect, it } from 'vitest';
import type { StructureEdge, StructureNode } from '../../api/structure';
import {
  computeLayerMap,
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
    is_deferred: false,
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

  it('sets generating attribute when generation_running is true', () => {
    const elements = topLevelElements(
      [n('comp_C1', 'comp', null, { generation_running: true })],
      [],
    );
    const data = elements[0].data as { generating?: string };
    expect(data.generating).toBe('1');
  });

  it('omits generating attribute when generation_running is false', () => {
    const elements = topLevelElements(
      [n('comp_C1', 'comp', null, { generation_running: false })],
      [],
    );
    const data = elements[0].data as { generating?: string };
    expect(data.generating).toBeUndefined();
  });

  it('dispatches presentational comps to comp-top-presentational type', () => {
    const elements = topLevelElements(
      [
        n('comp_dom', 'comp', null, { kind: 'domain' }),
        n('comp_pres', 'comp', null, { kind: 'presentational' }),
      ],
      [],
    );
    const byId: Record<string, string> = {};
    for (const el of elements) {
      const d = el.data as { id?: string; type?: string };
      if (d.id && d.type) byId[d.id] = d.type;
    }
    expect(byId.comp_dom).toBe('comp-top');
    expect(byId.comp_pres).toBe('comp-top-presentational');
  });

  it('rolls up policy_application target from a subcomp to its top-level parent', () => {
    // The subcomp is filtered out of the top-level view, but the
    // policy still needs to connect somewhere visible. Roll up to
    // the top-level parent comp so the policy isn't floating
    // disconnected.
    const nodes = [
      n('policy_P1', 'policy', null),
      n('comp_TOP', 'comp', null),
      n('comp_SUB', 'comp', 'comp_TOP'),
    ];
    const edges = [e('edge_1', 'policy_application', 'policy_P1', 'comp_SUB')];
    const elements = topLevelElements(nodes, edges);
    // Subcomp is filtered out; top-level comp + policy stay.
    const nodeIds = elements
      .map((el) => (el.data as { id?: string; source?: string }).id)
      .filter((id): id is string => !!id && !id.startsWith('edge_'));
    expect(nodeIds).toContain('policy_P1');
    expect(nodeIds).toContain('comp_TOP');
    expect(nodeIds).not.toContain('comp_SUB');
    // The edge target gets rewritten to the rolled-up parent.
    const edgeData = elements
      .map((el) => el.data as { source?: string; target?: string; edgeType?: string })
      .find((d) => d.source === 'policy_P1');
    expect(edgeData).toBeDefined();
    expect(edgeData?.target).toBe('comp_TOP');
    expect(edgeData?.edgeType).toBe('policy_application');
  });

  it('dedupes rolled-up policy edges when multiple subcomps share a parent', () => {
    // If the same policy applies to two subcomps under the same
    // parent comp, both edges roll up to the same source/target
    // pair. Only one edge should render.
    const nodes = [
      n('policy_P1', 'policy', null),
      n('comp_TOP', 'comp', null),
      n('comp_SUB1', 'comp', 'comp_TOP'),
      n('comp_SUB2', 'comp', 'comp_TOP'),
    ];
    const edges = [
      e('edge_1', 'policy_application', 'policy_P1', 'comp_SUB1'),
      e('edge_2', 'policy_application', 'policy_P1', 'comp_SUB2'),
    ];
    const elements = topLevelElements(nodes, edges);
    const polEdges = elements
      .map((el) => el.data as { source?: string; target?: string; edgeType?: string })
      .filter((d) => d.edgeType === 'policy_application');
    expect(polEdges).toHaveLength(1);
    expect(polEdges[0].source).toBe('policy_P1');
    expect(polEdges[0].target).toBe('comp_TOP');
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

  it('includes subcomps / fanin / local policies', () => {
    const elements = drillElements(
      drilledId,
      [
        n(drilledId, 'comp', null),
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
    ]);
  });

  it('drops orphan subresps from the drill view', () => {
    // Pre-Phase-A subresps may linger as tier="resp" rows with
    // parent_id pointing at a comp; the drill walk should ignore
    // them so the decomposition graph stays clean.
    const elements = drillElements(
      drilledId,
      [
        n(drilledId, 'comp', null),
        n('resp_orphanSub', 'resp', drilledId),
      ],
      [],
    );
    expect(ids(elements)).not.toContain('resp_orphanSub');
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

describe('computeLayerMap', () => {
  it('places sources (no incoming edges) at layer 0', () => {
    const layers = computeLayerMap(
      [{ id: 'a', type: 'feat', parent_id: null }],
      [],
    );
    expect(layers.get('a')).toBe(0);
  });

  it('walks decomposition chain feat → resp → comp', () => {
    const layers = computeLayerMap(
      [
        { id: 'feat_F', type: 'feat', parent_id: null },
        { id: 'resp_R', type: 'resp-top', parent_id: null },
        { id: 'comp_C', type: 'comp-top', parent_id: null },
      ],
      [
        { source: 'feat_F', target: 'resp_R' },
        { source: 'resp_R', target: 'comp_C' },
      ],
    );
    expect(layers.get('feat_F')).toBe(0);
    expect(layers.get('resp_R')).toBe(1);
    expect(layers.get('comp_C')).toBe(2);
  });

  it('takes max(parent.layer) + 1 when a node has multiple parents', () => {
    // Diamond: foundation comp at L=2, dependee A also at L=2,
    // depender B has incoming from both → L=3.
    const layers = computeLayerMap(
      [
        { id: 'feat', type: 'feat', parent_id: null },
        { id: 'resp', type: 'resp-top', parent_id: null },
        { id: 'foundation', type: 'comp-top', parent_id: null },
        { id: 'a', type: 'comp-top', parent_id: null },
        { id: 'b', type: 'comp-top', parent_id: null },
      ],
      [
        { source: 'feat', target: 'resp' },
        { source: 'resp', target: 'foundation' },
        { source: 'resp', target: 'a' },
        { source: 'resp', target: 'b' },
        // dep edges (post-flip in cytoscape: dependee → depender).
        { source: 'foundation', target: 'a' },
        { source: 'foundation', target: 'b' },
        { source: 'a', target: 'b' },
      ],
    );
    expect(layers.get('foundation')).toBe(2);
    expect(layers.get('a')).toBe(3); // resp(1)+1=2, foundation(2)+1=3 → max 3
    expect(layers.get('b')).toBe(4); // a(3)+1=4 wins over foundation+1 and resp+1
  });

  it('treats parent_id as an implicit decomposition edge', () => {
    // Drilled comp's only structural edge is from a resp. The
    // subcomp also has a structural edge from the same resp (Phase 4
    // comparch creates resp → subcomp directly). Without the
    // parent_id assist they'd land on the same layer. The implicit
    // parent_id edge from drilled comp → subcomp pushes the subcomp
    // one layer below the drilled comp.
    const layers = computeLayerMap(
      [
        { id: 'resp', type: 'external-resp', parent_id: null },
        { id: 'comp', type: 'comp-sub', parent_id: null },
        { id: 'sub', type: 'comp-sub', parent_id: 'comp' },
      ],
      [
        { source: 'resp', target: 'comp' },
        { source: 'resp', target: 'sub' },
      ],
    );
    // external-resp is pinned to layer 1, comp walks to 2 (resp+1),
    // sub walks to 3 (max(resp+1=2, comp+1=3) = 3 via the parent_id
    // implicit edge). The relative spacing comp < sub is what
    // matters here.
    expect(layers.get('resp')).toBe(1);
    expect(layers.get('comp')).toBe(2);
    expect(layers.get('sub')).toBe(3);
    expect(layers.get('sub')).toBeGreaterThan(layers.get('comp')!);
  });

  it('pins policy nodes to layer 1', () => {
    const layers = computeLayerMap(
      [
        { id: 'pt', type: 'policy-top', parent_id: null },
        { id: 'px', type: 'external-policy', parent_id: null },
        { id: 'pl', type: 'policy-local', parent_id: 'comp' },
        { id: 'comp', type: 'comp-sub', parent_id: null },
      ],
      [],
    );
    expect(layers.get('pt')).toBe(1);
    expect(layers.get('px')).toBe(1);
    expect(layers.get('pl')).toBe(1);
  });

  it('pins resp / external-resp to layer 1 even without a feat ancestor', () => {
    // Orphan-resp regression: a resp with no incoming feat edge
    // would walk to layer 0 and render in the feature row. Pin
    // forces it into the resp row.
    const layers = computeLayerMap(
      [
        { id: 'r1', type: 'resp-top', parent_id: null },
        { id: 'r2', type: 'external-resp', parent_id: null },
      ],
      [],
    );
    expect(layers.get('r1')).toBe(1);
    expect(layers.get('r2')).toBe(1);
  });

  it('pins feat / external-feat to layer 0', () => {
    const layers = computeLayerMap(
      [
        { id: 'f1', type: 'feat', parent_id: null },
        { id: 'f2', type: 'external-feat', parent_id: null },
      ],
      [],
    );
    expect(layers.get('f1')).toBe(0);
    expect(layers.get('f2')).toBe(0);
  });

  it('pins presentational comps to max-walk-layer + 1', () => {
    // Domain comps spread by dep depth via the walk; presentational
    // comps land in their own band one row below the deepest
    // domain layer regardless of their walked position.
    const layers = computeLayerMap(
      [
        { id: 'feat', type: 'feat', parent_id: null },
        { id: 'resp', type: 'resp-top', parent_id: null },
        { id: 'd1', type: 'comp-top', parent_id: null },
        { id: 'd2', type: 'comp-top', parent_id: null },
        { id: 'pres', type: 'comp-top-presentational', parent_id: null },
      ],
      [
        { source: 'feat', target: 'resp' },
        { source: 'resp', target: 'd1' },
        { source: 'resp', target: 'd2' },
        // d2 depends on d1 — pushes d2 one row below d1.
        { source: 'd1', target: 'd2' },
      ],
    );
    // walk: feat=0, resp=1 (pinned), d1=2, d2=3 (dep-deep)
    expect(layers.get('d1')).toBe(2);
    expect(layers.get('d2')).toBe(3);
    // presentational pins to max-walk + 1 = 4
    expect(layers.get('pres')).toBe(4);
  });

  it('pin overrides propagate to descendants (drilled-comp resp pin)', () => {
    // Regression: an earlier post-walk pin left descendants with
    // stale walk-derived layers. Ensure that with the pin applied
    // during the walk, a comp downstream of a pinned external-resp
    // gets the pinned-aware layer.
    const layers = computeLayerMap(
      [
        { id: 'resp', type: 'external-resp', parent_id: null },
        { id: 'comp', type: 'comp-sub', parent_id: null },
      ],
      [{ source: 'resp', target: 'comp' }],
    );
    // resp pinned to 1; comp walks to resp+1 = 2 (NOT 1 from the
    // pre-pin walk).
    expect(layers.get('resp')).toBe(1);
    expect(layers.get('comp')).toBe(2);
  });

  it('pins fanin to max-walk-layer + 1', () => {
    const layers = computeLayerMap(
      [
        { id: 'feat', type: 'feat', parent_id: null },
        { id: 'resp', type: 'resp-top', parent_id: null },
        { id: 'comp', type: 'comp-top', parent_id: null },
        { id: 'sub', type: 'comp-sub', parent_id: 'comp' },
        { id: 'impl', type: 'impl', parent_id: 'sub' },
        { id: 'fan', type: 'fanin', parent_id: 'comp' },
      ],
      [
        { source: 'feat', target: 'resp' },
        { source: 'resp', target: 'comp' },
      ],
    );
    // walk: feat=0, resp=1, comp=2, sub=3 (parent_id), impl=4 (parent_id).
    // fan would be 3 from parent_id alone, but the special case
    // pushes it to max + 1 = 5.
    expect(layers.get('impl')).toBe(4);
    expect(layers.get('fan')).toBe(5);
  });

  it('falls back to 0 for nodes left unassigned (cycle / disconnected)', () => {
    // Self-edges are ignored (so they don't form a cycle), but a
    // 2-node cycle would leave both nodes unassigned. Both land at
    // 0 via the safety pass.
    const layers = computeLayerMap(
      [
        { id: 'x', type: 'comp-top', parent_id: null },
        { id: 'y', type: 'comp-top', parent_id: null },
      ],
      [
        { source: 'x', target: 'y' },
        { source: 'y', target: 'x' },
      ],
    );
    expect(layers.get('x')).toBe(0);
    expect(layers.get('y')).toBe(0);
  });
});
