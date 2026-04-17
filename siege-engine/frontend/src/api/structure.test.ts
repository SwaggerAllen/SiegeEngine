import { describe, expect, it } from 'vitest';
import { StructureResponseSchema } from './structure';

describe('StructureResponseSchema', () => {
  it('parses the minimum valid response', () => {
    const raw = {
      offset: 0,
      nodes: [],
      edges: [],
    };
    const parsed = StructureResponseSchema.parse(raw);
    expect(parsed.offset).toBe(0);
    expect(parsed.nodes).toEqual([]);
    expect(parsed.edges).toEqual([]);
  });

  it('parses a response with nodes + edges', () => {
    const raw = {
      offset: 42,
      nodes: [
        {
          id: 'comp_A',
          tier: 'comp',
          kind: 'domain',
          parent_id: null,
          name: 'Billing',
          display_order: 0,
          content: '',
          has_content: true,
          has_pending_draft: false,
          generation_running: true,
        },
        {
          id: 'resp_X',
          tier: 'resp',
          kind: 'domain',
          parent_id: 'comp_A',
          name: 'Session minting',
          display_order: 0,
          content: 'Mint session tokens.',
          has_content: true,
          has_pending_draft: false,
          generation_running: false,
        },
      ],
      edges: [
        {
          id: 'edge_1',
          edge_type: 'decomposition',
          source_id: 'resp_top',
          target_id: 'comp_A',
        },
      ],
    };
    const parsed = StructureResponseSchema.parse(raw);
    expect(parsed.offset).toBe(42);
    expect(parsed.nodes).toHaveLength(2);
    expect(parsed.nodes[0].generation_running).toBe(true);
    expect(parsed.nodes[1].content).toBe('Mint session tokens.');
    expect(parsed.edges[0].edge_type).toBe('decomposition');
  });

  it('rejects a node missing content', () => {
    const raw = {
      offset: 0,
      nodes: [
        {
          id: 'comp_A',
          tier: 'comp',
          kind: 'domain',
          parent_id: null,
          name: 'B',
          display_order: 0,
          // content missing
          has_content: false,
          has_pending_draft: false,
          generation_running: false,
        },
      ],
      edges: [],
    };
    expect(() => StructureResponseSchema.parse(raw)).toThrow();
  });
});
