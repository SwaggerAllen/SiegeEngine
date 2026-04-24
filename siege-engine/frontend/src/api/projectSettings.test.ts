import { describe, it, expect } from 'vitest';
import { ProjectSettingsSchema } from './projectSettings';

describe('ProjectSettingsSchema', () => {
  it('parses a valid payload', () => {
    const parsed = ProjectSettingsSchema.parse({
      generation_timeout_seconds: 900,
      cli_max_budget_usd: 2.0,
      cli_max_output_tokens: 64000,
    });
    expect(parsed.generation_timeout_seconds).toBe(900);
    expect(parsed.cli_max_budget_usd).toBe(2.0);
    expect(parsed.cli_max_output_tokens).toBe(64000);
  });

  it('rejects a timeout below the minimum', () => {
    expect(() =>
      ProjectSettingsSchema.parse({
        generation_timeout_seconds: 10,
        cli_max_budget_usd: 2.0,
        cli_max_output_tokens: 128000,
      })
    ).toThrow();
  });

  it('rejects a timeout above the maximum', () => {
    expect(() =>
      ProjectSettingsSchema.parse({
        generation_timeout_seconds: 99999,
        cli_max_budget_usd: 2.0,
        cli_max_output_tokens: 128000,
      })
    ).toThrow();
  });

  it('rejects a budget below the minimum', () => {
    expect(() =>
      ProjectSettingsSchema.parse({
        generation_timeout_seconds: 900,
        cli_max_budget_usd: 0.0,
        cli_max_output_tokens: 128000,
      })
    ).toThrow();
  });

  it('rejects a budget above the maximum', () => {
    expect(() =>
      ProjectSettingsSchema.parse({
        generation_timeout_seconds: 900,
        cli_max_budget_usd: 1000,
        cli_max_output_tokens: 128000,
      })
    ).toThrow();
  });

  it('rejects max output tokens below the minimum', () => {
    expect(() =>
      ProjectSettingsSchema.parse({
        generation_timeout_seconds: 900,
        cli_max_budget_usd: 2.0,
        cli_max_output_tokens: 500,
      })
    ).toThrow();
  });

  it('rejects max output tokens above the maximum', () => {
    expect(() =>
      ProjectSettingsSchema.parse({
        generation_timeout_seconds: 900,
        cli_max_budget_usd: 2.0,
        cli_max_output_tokens: 9999999,
      })
    ).toThrow();
  });
});
