import { z } from 'zod';
import api from './client';

// Phase 11 — pending-change queue client.
//
// Every UI edit affordance enqueues one of 16 structured instruction
// types (see backend/graph/instructions.py). Nothing mutates the
// model directly — the backend applies them as a batch when the
// user clicks "Apply changes" on the Queue panel.

export const InstructionStatusSchema = z.enum([
  'queued',
  'running',
  'applied',
  'discarded',
  'failed',
]);
export type InstructionStatus = z.infer<typeof InstructionStatusSchema>;

// Structured instruction payloads — mirror of the Pydantic
// discriminated union in backend/graph/instructions.py.
const _BaseInstr = z.object({ instruction_type: z.string() });

export const CreateInstruction = _BaseInstr.extend({
  instruction_type: z.literal('Create'),
  node_id: z.string(),
  tier: z.string(),
  name: z.string(),
  parent_id: z.string().nullable().optional(),
  parent_name: z.string().nullable().optional(),
});

export const DeleteInstruction = _BaseInstr.extend({
  instruction_type: z.literal('Delete'),
  node_id: z.string(),
  name: z.string(),
});

export const RenameInstruction = _BaseInstr.extend({
  instruction_type: z.literal('Rename'),
  node_id: z.string(),
  old_name: z.string(),
  new_name: z.string(),
});

export const ReassignMappingInstruction = _BaseInstr.extend({
  instruction_type: z.literal('ReassignMapping'),
  node_id: z.string(),
  name: z.string(),
  new_parent_id: z.string().nullable(),
  new_parent_name: z.string().nullable(),
});

const EndpointInstr = _BaseInstr.extend({
  source_id: z.string(),
  source_name: z.string(),
  target_id: z.string(),
  target_name: z.string(),
});

export const AddDependencyInstruction = EndpointInstr.extend({
  instruction_type: z.literal('AddDependency'),
});
export const RemoveDependencyInstruction = EndpointInstr.extend({
  instruction_type: z.literal('RemoveDependency'),
});
export const AddDomainParentInstruction = EndpointInstr.extend({
  instruction_type: z.literal('AddDomainParent'),
});
export const RemoveDomainParentInstruction = EndpointInstr.extend({
  instruction_type: z.literal('RemoveDomainParent'),
});
export const AddDecompositionInstruction = EndpointInstr.extend({
  instruction_type: z.literal('AddDecomposition'),
});
export const RemoveDecompositionInstruction = EndpointInstr.extend({
  instruction_type: z.literal('RemoveDecomposition'),
});

export const InstructionSchema = z.discriminatedUnion('instruction_type', [
  CreateInstruction,
  DeleteInstruction,
  RenameInstruction,
  ReassignMappingInstruction,
  AddDependencyInstruction,
  RemoveDependencyInstruction,
  AddDomainParentInstruction,
  RemoveDomainParentInstruction,
  AddDecompositionInstruction,
  RemoveDecompositionInstruction,
]);
export type Instruction = z.infer<typeof InstructionSchema>;

export const InstructionRowSchema = z.object({
  id: z.string(),
  sequence: z.number().int(),
  instruction_type: z.string(),
  payload: z.record(z.string(), z.unknown()),
  status: InstructionStatusSchema,
  error: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  rendered: z.string(),
});
export type InstructionRow = z.infer<typeof InstructionRowSchema>;

export const QueueStateSchema = z.object({
  queued: z.array(InstructionRowSchema),
  running: z.array(InstructionRowSchema),
  failed: z.array(InstructionRowSchema),
  recent_applied: z.array(InstructionRowSchema),
  apply_in_flight: z.boolean(),
});
export type QueueState = z.infer<typeof QueueStateSchema>;

export async function getQueue(projectId: string): Promise<QueueState> {
  const { data } = await api.get(`/projects/${projectId}/queue`);
  return QueueStateSchema.parse(data);
}

export async function enqueueInstruction(
  projectId: string,
  instruction: Instruction,
): Promise<{ id: string; sequence: number }> {
  const { data } = await api.post(`/projects/${projectId}/queue/enqueue`, {
    instruction,
  });
  return z.object({ id: z.string(), sequence: z.number().int() }).parse(data);
}

export async function applyQueue(
  projectId: string,
): Promise<{ job_id: string | null; applied: number }> {
  const { data } = await api.post(`/projects/${projectId}/queue/apply`);
  return z
    .object({ job_id: z.string().nullable(), applied: z.number().int() })
    .parse(data);
}

export async function discardAll(
  projectId: string,
): Promise<{ discarded: number }> {
  const { data } = await api.post(`/projects/${projectId}/queue/discard`);
  return z.object({ discarded: z.number().int() }).parse(data);
}

export async function discardOne(
  projectId: string,
  instructionId: string,
): Promise<void> {
  await api.delete(`/projects/${projectId}/queue/${instructionId}`);
}

export async function retryInstruction(
  projectId: string,
  instructionId: string,
): Promise<void> {
  await api.post(`/projects/${projectId}/queue/${instructionId}/retry`);
}
