import { describe, expect, it } from 'vitest';
import type { ProjectGraph } from '../api/siege';
import { v3ToLegacyStructure } from './v3ToLegacyStructure';

function graph(over: Partial<ProjectGraph>): ProjectGraph {
  return {
    ref: 'main',
    ref_head_sha: '0'.repeat(40),
    nodes: [],
    edges: [],
    ...over,
  };
}

describe('v3ToLegacyStructure', () => {
  it('maps v3 tiers onto the legacy short names', () => {
    const out = v3ToLegacyStructure(
      graph({
        nodes: [
          {
            id: 'feat_a',
            tier: 'feature_expansion',
            kind: 'feature',
            name: 'Login',
            parent_id: null,
            order: 0,
            is_foundation: false,
            implicit: false,
            status: 'approved',
            score: null,
            has_body: true,
          },
          {
            id: 'resp_x',
            tier: 'requirements',
            kind: 'responsibility',
            name: 'Auth',
            parent_id: null,
            order: 0,
            is_foundation: false,
            implicit: false,
            status: 'approved',
            score: null,
            has_body: true,
          },
          {
            id: 'comp_b',
            tier: 'sysarch',
            kind: 'component',
            name: 'Billing',
            parent_id: null,
            order: 0,
            is_foundation: false,
            implicit: false,
            status: 'drafted',
            score: null,
            has_body: true,
          },
          {
            id: 'comp_s',
            tier: 'comparch',
            kind: 'subcomponent',
            name: 'Store',
            parent_id: 'comp_b',
            order: 0,
            is_foundation: false,
            implicit: false,
            status: 'absent',
            score: null,
            has_body: false,
          },
        ],
      }),
    );
    const byId = Object.fromEntries(out.nodes.map((n) => [n.id, n]));
    expect(byId['feat_a'].tier).toBe('feat');
    expect(byId['resp_x'].tier).toBe('resp');
    expect(byId['comp_b'].tier).toBe('comp');
    expect(byId['comp_s'].tier).toBe('comp');
    expect(byId['comp_s'].parent_id).toBe('comp_b');
  });

  it("marks any comp that's a source of a domain_parent edge as presentational", () => {
    const out = v3ToLegacyStructure(
      graph({
        nodes: [
          {
            id: 'comp_ui',
            tier: 'sysarch',
            kind: 'component',
            name: 'BillingUI',
            parent_id: null,
            order: 0,
            is_foundation: false,
            implicit: false,
            status: 'absent',
            score: null,
            has_body: false,
          },
          {
            id: 'comp_billing',
            tier: 'sysarch',
            kind: 'component',
            name: 'Billing',
            parent_id: null,
            order: 1,
            is_foundation: false,
            implicit: false,
            status: 'drafted',
            score: null,
            has_body: true,
          },
        ],
        edges: [
          {
            id: 'domain_parent:comp_ui->comp_billing',
            type: 'domain_parent',
            source_id: 'comp_ui',
            target_id: 'comp_billing',
          },
        ],
      }),
    );
    const byId = Object.fromEntries(out.nodes.map((n) => [n.id, n]));
    expect(byId['comp_ui'].kind).toBe('presentational');
    expect(byId['comp_billing'].kind).toBe('domain');
  });

  it('renames edge.type to edge.edge_type', () => {
    const out = v3ToLegacyStructure(
      graph({
        edges: [
          {
            id: 'dep:a->b',
            type: 'dependency',
            source_id: 'comp_a',
            target_id: 'comp_b',
          },
          {
            id: 'decomp:feat_a->resp_x',
            type: 'decomposition',
            source_id: 'feat_a',
            target_id: 'resp_x',
          },
        ],
      }),
    );
    expect(out.edges.map((e) => e.edge_type).sort()).toEqual([
      'decomposition',
      'dependency',
    ]);
  });

  it("maps policy nodes to legacy tier='policy' with kind='policy'", () => {
    // The v3 projection emits policies under tier='sysarch' with
    // kind='policy'; the legacy taxonomy treats them as their own
    // tier so the DAG's policy-top styling + sidebar's comp filter
    // both behave correctly.
    const out = v3ToLegacyStructure(
      graph({
        nodes: [
          {
            id: 'policy_audit',
            tier: 'sysarch',
            kind: 'policy',
            name: 'Audit Every Privileged Action',
            parent_id: null,
            order: 0,
            is_foundation: false,
            implicit: false,
            status: 'approved',
            score: null,
            has_body: false,
          },
        ],
      }),
    );
    expect(out.nodes[0].tier).toBe('policy');
    expect(out.nodes[0].kind).toBe('policy');
  });

  it('fills the lifecycle defaults v3 nodes do not carry', () => {
    const out = v3ToLegacyStructure(
      graph({
        nodes: [
          {
            id: 'feat_a',
            tier: 'feature_expansion',
            kind: 'feature',
            name: 'Login',
            parent_id: null,
            order: 0,
            is_foundation: false,
            implicit: false,
            status: 'drafted',
            score: null,
            has_body: true,
          },
        ],
      }),
    );
    const n = out.nodes[0];
    expect(n.has_pending_draft).toBe(true); // drafted maps over
    expect(n.has_content).toBe(true); // from has_body
    expect(n.generation_running).toBe(false);
    expect(n.has_error).toBe(false);
    expect(n.is_stale).toBe(false);
    expect(n.staleness_reasons).toEqual([]);
    expect(n.is_deferred).toBe(false);
  });
});
