import { describe, expect, it } from 'vitest';
import { FanInResponseSchema } from './fanin';

// Validate that the zod schema accepts the backend's
// FanInResponse Pydantic model. Fan-in has no draft lifecycle,
// so the shape is strictly {node, generation_status, telemetry,
// error, attempt-counter fields} — no pending_draft field.

describe('FanInResponseSchema', () => {
  it('parses the minimum valid response', () => {
    const raw = {
      node: {
        id: 'fanin_AAAAAAAA',
        name: 'Billing fan-in',
        owner_comp_id: 'comp_BBBBBBBB',
        content: '',
        updated_at: '2026-04-17T00:00:00',
      },
      generation_status: 'idle',
      last_error: null,
      latest_telemetry: null,
    };
    const parsed = FanInResponseSchema.parse(raw);
    expect(parsed.node.id).toBe('fanin_AAAAAAAA');
    expect(parsed.node.owner_comp_id).toBe('comp_BBBBBBBB');
    expect(parsed.generation_started_at).toBeNull();
    expect(parsed.current_attempt).toBeNull();
  });

  it('parses a running-state response with telemetry', () => {
    const raw = {
      node: {
        id: 'fanin_A',
        name: 'fanin',
        owner_comp_id: 'comp_B',
        content: '<fanin>body</fanin>',
        updated_at: '2026-04-17T00:00:00',
      },
      generation_status: 'running',
      last_error: null,
      latest_telemetry: {
        prompt_tokens: 100,
        completion_tokens: 50,
        model: 'claude-sonnet-4-6',
        created_at: '2026-04-17T00:00:00',
      },
      generation_started_at: '2026-04-17T00:00:00',
      current_attempt: 1,
      max_attempts: 3,
    };
    const parsed = FanInResponseSchema.parse(raw);
    expect(parsed.node.content).toContain('<fanin>');
    expect(parsed.generation_status).toBe('running');
    expect(parsed.latest_telemetry?.model).toBe('claude-sonnet-4-6');
    expect(parsed.current_attempt).toBe(1);
    expect(parsed.max_attempts).toBe(3);
  });

  it('parses a failed-state response with last_error', () => {
    const raw = {
      node: {
        id: 'fanin_A',
        name: 'fanin',
        owner_comp_id: 'comp_B',
        content: '',
        updated_at: '2026-04-17T00:00:00',
      },
      generation_status: 'failed',
      last_error: 'Parse retries exhausted',
      latest_telemetry: null,
      failed_raw_output: '<fanin>broken',
    };
    const parsed = FanInResponseSchema.parse(raw);
    expect(parsed.generation_status).toBe('failed');
    expect(parsed.last_error).toBe('Parse retries exhausted');
    expect(parsed.failed_raw_output).toContain('broken');
  });

  it('rejects a missing owner_comp_id field', () => {
    const raw = {
      node: {
        id: 'fanin_A',
        name: 'fanin',
        // owner_comp_id missing
        content: '',
        updated_at: '2026-04-17T00:00:00',
      },
      generation_status: 'idle',
      last_error: null,
      latest_telemetry: null,
    };
    expect(() => FanInResponseSchema.parse(raw)).toThrow();
  });
});
