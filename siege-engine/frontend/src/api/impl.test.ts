import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ImplResponseSchema } from './impl';

// Validate that the zod schema accepts the backend's canonical
// response shape. The schema is the client-side contract with
// the ImplResponse Pydantic model on the backend.

describe('ImplResponseSchema', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('parses the minimum valid response', () => {
    const raw = {
      node: {
        id: 'impl_AAAAAAAA',
        name: 'Impl',
        parent_id: 'comp_BBBBBBBB',
        content: '',
        updated_at: '2026-04-17T00:00:00',
      },
      pending_draft: null,
      generation_status: 'idle',
      last_error: null,
      latest_telemetry: null,
      generation_started_at: null,
    };
    const parsed = ImplResponseSchema.parse(raw);
    expect(parsed.node.id).toBe('impl_AAAAAAAA');
    expect(parsed.node.parent_id).toBe('comp_BBBBBBBB');
    expect(parsed.pending_draft).toBeNull();
  });

  it('parses a response with a pending draft', () => {
    const raw = {
      node: {
        id: 'impl_A',
        name: 'Impl',
        parent_id: 'comp_B',
        content: '',
        updated_at: '2026-04-17T00:00:00',
      },
      pending_draft: {
        id: 'draft_1',
        content: '<implementation/>',
        created_at: '2026-04-17T00:00:00',
      },
      generation_status: 'running',
      last_error: null,
      latest_telemetry: null,
      generation_started_at: '2026-04-17T00:00:00',
    };
    const parsed = ImplResponseSchema.parse(raw);
    expect(parsed.pending_draft?.id).toBe('draft_1');
    expect(parsed.generation_status).toBe('running');
  });

  it('coerces undefined generation_started_at to null', () => {
    const raw = {
      node: {
        id: 'impl_A',
        name: 'Impl',
        parent_id: 'comp_B',
        content: '',
        updated_at: '2026-04-17T00:00:00',
      },
      pending_draft: null,
      generation_status: 'idle',
      last_error: null,
      latest_telemetry: null,
      // generation_started_at omitted
    };
    const parsed = ImplResponseSchema.parse(raw);
    expect(parsed.generation_started_at).toBeNull();
  });

  it('rejects a missing node field', () => {
    const raw = {
      node: {
        id: 'impl_A',
        name: 'Impl',
        // parent_id missing
        content: '',
        updated_at: '2026-04-17T00:00:00',
      },
      pending_draft: null,
      generation_status: 'idle',
      last_error: null,
      latest_telemetry: null,
      generation_started_at: null,
    };
    expect(() => ImplResponseSchema.parse(raw)).toThrow();
  });
});
