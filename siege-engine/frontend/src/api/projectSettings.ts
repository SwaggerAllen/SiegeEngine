import { z } from 'zod';
import api from './client';

// Mirror of backend/projects/settings.py NodeCountRange. Must stay
// aligned with the backend pydantic model: every value is a
// positive integer up to 1000, and the four must be ordered
// ``floor <= typical_min <= typical_max <= ceiling``. The
// ``.refine`` below matches the ``model_validator`` on the backend
// so a client submission fails fast with the same shape the
// server would reject.
export const NodeCountRangeSchema = z
  .object({
    floor: z.number().int().min(1).max(1000),
    typical_min: z.number().int().min(1).max(1000),
    typical_max: z.number().int().min(1).max(1000),
    ceiling: z.number().int().min(1).max(1000),
  })
  .refine(
    (v) =>
      v.floor <= v.typical_min &&
      v.typical_min <= v.typical_max &&
      v.typical_max <= v.ceiling,
    {
      message: 'Values must be ordered floor ≤ typical min ≤ typical max ≤ ceiling',
    }
  );

export type NodeCountRange = z.infer<typeof NodeCountRangeSchema>;

// Defaults match backend/projects/settings.py. The frontend
// ``.default()`` on each nested field lets the tests mock the
// timeout only without hand-rolling a full ProjectSettings blob,
// and it mirrors the backend's own tolerance for partially
// populated settings dicts.
export const DEFAULT_FEATURES_PER_GROUP: NodeCountRange = {
  floor: 2,
  typical_min: 3,
  typical_max: 8,
  ceiling: 15,
};
export const DEFAULT_TOP_LEVEL_RESPONSIBILITIES: NodeCountRange = {
  floor: 3,
  typical_min: 8,
  typical_max: 20,
  ceiling: 40,
};
export const DEFAULT_TOP_LEVEL_COMPONENTS: NodeCountRange = {
  floor: 3,
  typical_min: 5,
  typical_max: 15,
  ceiling: 25,
};
export const DEFAULT_SUBCOMPONENTS_PER_COMPONENT: NodeCountRange = {
  floor: 1,
  typical_min: 2,
  typical_max: 8,
  ceiling: 15,
};
export const DEFAULT_SUBRESPONSIBILITIES_PER_COMPONENT: NodeCountRange = {
  floor: 3,
  typical_min: 4,
  typical_max: 12,
  ceiling: 30,
};

// Mirror of backend/projects/settings.py ProjectSettings. Keep the
// bounds aligned with the backend pydantic Field constraints so the
// frontend validates client-side before the round trip.
export const ProjectSettingsSchema = z.object({
  generation_timeout_seconds: z.number().int().min(60).max(3600),
  features_per_group: NodeCountRangeSchema.default(DEFAULT_FEATURES_PER_GROUP),
  top_level_responsibilities: NodeCountRangeSchema.default(
    DEFAULT_TOP_LEVEL_RESPONSIBILITIES
  ),
  top_level_components: NodeCountRangeSchema.default(DEFAULT_TOP_LEVEL_COMPONENTS),
  subcomponents_per_component: NodeCountRangeSchema.default(
    DEFAULT_SUBCOMPONENTS_PER_COMPONENT
  ),
  subresponsibilities_per_component: NodeCountRangeSchema.default(
    DEFAULT_SUBRESPONSIBILITIES_PER_COMPONENT
  ),
});
export type ProjectSettings = z.infer<typeof ProjectSettingsSchema>;

export async function getProjectSettings(projectId: string): Promise<ProjectSettings> {
  const { data } = await api.get(`/projects/${projectId}/settings`);
  return ProjectSettingsSchema.parse(data);
}

export async function updateProjectSettings(
  projectId: string,
  settings: ProjectSettings
): Promise<ProjectSettings> {
  const { data } = await api.put(`/projects/${projectId}/settings`, settings);
  return ProjectSettingsSchema.parse(data);
}

// Per-tier metadata used by the settings page to render each
// NodeCountRange sub-form. Kept next to the schema so the UI and
// the contract evolve together. The field name must match the
// ProjectSettings key so the page can index into the form state
// generically.
export interface NodeCountRangeField {
  key:
    | 'features_per_group'
    | 'top_level_responsibilities'
    | 'top_level_components'
    | 'subcomponents_per_component'
    | 'subresponsibilities_per_component';
  label: string;
  description: string;
}

export const NODE_COUNT_RANGE_FIELDS: readonly NodeCountRangeField[] = [
  {
    key: 'features_per_group',
    label: 'Features per group',
    description:
      'How many features should sit inside a named feature group during the expansion pass. Below the floor, groups should be inlined; above the ceiling, they should split along a sub-theme.',
  },
  {
    key: 'top_level_responsibilities',
    label: 'Top-level responsibilities',
    description:
      'How many top-level responsibilities the requirements pass should produce for this project. Below the floor, decomposition is too coarse; above the ceiling, the LLM is reaching into implementation territory.',
  },
  {
    key: 'top_level_components',
    label: 'Top-level components',
    description:
      'How many top-level components (excluding the foundation) sysarch should produce. Below the floor, decomposition is too coarse; above the ceiling, components belong in Phase 4 arch docs.',
  },
  {
    key: 'subcomponents_per_component',
    label: 'Subcomponents per component',
    description:
      'How many subcomponents (including the foundation) comparch should produce per top-level component. Below the floor, un-fanned-out is cleaner; above the ceiling, the LLM is reaching into implementation detail.',
  },
  {
    key: 'subresponsibilities_per_component',
    label: 'Subresponsibilities per component',
    description:
      'How many subresponsibilities the subrequirements pass should produce per component. Below the floor, not decomposing enough; above the ceiling, reaching into implementation detail.',
  },
];
