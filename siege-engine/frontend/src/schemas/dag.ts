import { z } from 'zod';

export const PromptInfoSchema = z.object({
  stage_key: z.string(),
  model: z.string().nullable(),
  has_custom_config: z.boolean(),
  template_key: z.string(),
});

export const DAGNodeDataSchema = z.object({
  label: z.string(),
  artifact_type: z.string(),
  status: z.string(),
  is_stale: z.boolean().optional().default(false),
  component_key: z.string().nullable(),
  version: z.number(),
  stage_key: z.string(),
  is_active: z.boolean(),
  has_artifact: z.boolean(),
  prompt_info: PromptInfoSchema.nullable().optional(),
  execution_id: z.string().nullable().optional(),
  execution_status: z.string().nullable().optional(),
  domain_parents: z.array(z.string()).nullable().optional(),
  dag_type: z.string().optional(),
});

export const DAGResponseSchema = z.object({
  nodes: z.array(z.object({
    id: z.string(),
    type: z.string(),
    data: DAGNodeDataSchema,
    position: z.object({ x: z.number(), y: z.number() }),
  })),
  edges: z.array(z.object({
    id: z.string(),
    source: z.string(),
    target: z.string(),
    type: z.string(),
    animated: z.boolean(),
  })),
});

export type PromptInfo = z.infer<typeof PromptInfoSchema>;
export type DAGNodeData = z.infer<typeof DAGNodeDataSchema>;
export type DAGResponse = z.infer<typeof DAGResponseSchema>;

/** Artifact types that represent component/sub-component fan-out maps. */
export const MAP_ARTIFACT_TYPES = new Set([
  'component_map',
  'sub_component_map',
  'frontend_component_map',
  'frontend_sub_component_map',
]);
