import { describe, it, expect } from 'vitest';
import { ProjectSettingsSchema } from './projectSettings';

describe('ProjectSettingsSchema', () => {
  it('parses a valid timeout', () => {
    const parsed = ProjectSettingsSchema.parse({
      generation_timeout_seconds: 900,
    });
    expect(parsed.generation_timeout_seconds).toBe(900);
  });

  it('rejects a timeout below the minimum', () => {
    expect(() =>
      ProjectSettingsSchema.parse({
        generation_timeout_seconds: 10,
      })
    ).toThrow();
  });

  it('rejects a timeout above the maximum', () => {
    expect(() =>
      ProjectSettingsSchema.parse({
        generation_timeout_seconds: 99999,
      })
    ).toThrow();
  });
});
