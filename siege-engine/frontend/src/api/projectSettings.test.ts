import { describe, it, expect } from 'vitest';
import {
  NodeCountRangeSchema,
  ProjectSettingsSchema,
  DEFAULT_FEATURES_PER_GROUP,
  DEFAULT_TOP_LEVEL_COMPONENTS,
} from './projectSettings';

describe('NodeCountRangeSchema', () => {
  it('parses a well-ordered range', () => {
    const parsed = NodeCountRangeSchema.parse({
      floor: 3,
      typical_min: 8,
      typical_max: 20,
      ceiling: 40,
    });
    expect(parsed.floor).toBe(3);
    expect(parsed.ceiling).toBe(40);
  });

  it('accepts an all-equal range', () => {
    const parsed = NodeCountRangeSchema.parse({
      floor: 5,
      typical_min: 5,
      typical_max: 5,
      ceiling: 5,
    });
    expect(parsed.ceiling).toBe(5);
  });

  it('rejects floor > typical_min', () => {
    expect(() =>
      NodeCountRangeSchema.parse({
        floor: 10,
        typical_min: 5,
        typical_max: 15,
        ceiling: 25,
      })
    ).toThrow();
  });

  it('rejects typical_max > ceiling', () => {
    expect(() =>
      NodeCountRangeSchema.parse({
        floor: 1,
        typical_min: 2,
        typical_max: 30,
        ceiling: 20,
      })
    ).toThrow();
  });

  it('rejects zero floor', () => {
    expect(() =>
      NodeCountRangeSchema.parse({
        floor: 0,
        typical_min: 1,
        typical_max: 2,
        ceiling: 3,
      })
    ).toThrow();
  });

  it('rejects values above the max', () => {
    expect(() =>
      NodeCountRangeSchema.parse({
        floor: 1,
        typical_min: 2,
        typical_max: 3,
        ceiling: 9999,
      })
    ).toThrow();
  });
});

describe('ProjectSettingsSchema', () => {
  it('fills NodeCountRange defaults when the backend omits them', () => {
    // Backend always returns a fully-populated object today, but
    // old test mocks and legacy responses may ship only the
    // timeout field. The frontend .default()s should cover that
    // case so downstream consumers always see all five ranges.
    const parsed = ProjectSettingsSchema.parse({
      generation_timeout_seconds: 900,
    });
    expect(parsed.features_per_group).toEqual(DEFAULT_FEATURES_PER_GROUP);
    expect(parsed.top_level_components).toEqual(DEFAULT_TOP_LEVEL_COMPONENTS);
  });

  it('preserves an explicit override', () => {
    const parsed = ProjectSettingsSchema.parse({
      generation_timeout_seconds: 1200,
      top_level_components: {
        floor: 4,
        typical_min: 6,
        typical_max: 10,
        ceiling: 20,
      },
    });
    expect(parsed.top_level_components.floor).toBe(4);
    expect(parsed.top_level_components.ceiling).toBe(20);
    // Untouched tiers keep their defaults.
    expect(parsed.features_per_group).toEqual(DEFAULT_FEATURES_PER_GROUP);
  });

  it('rejects an override with bad ordering', () => {
    expect(() =>
      ProjectSettingsSchema.parse({
        generation_timeout_seconds: 900,
        top_level_components: {
          floor: 30,
          typical_min: 5,
          typical_max: 15,
          ceiling: 25,
        },
      })
    ).toThrow();
  });

  it('rejects a timeout below the minimum', () => {
    expect(() =>
      ProjectSettingsSchema.parse({
        generation_timeout_seconds: 10,
      })
    ).toThrow();
  });
});
