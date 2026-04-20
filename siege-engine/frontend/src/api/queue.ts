import { z } from 'zod';
import api from './client';

/**
 * Phase 11 — pending-change queue API.
 *
 * The frontend mirrors the 14 backend instruction types as a
 * discriminated union via ``instruction_type``. Each schema
 * is intentionally minimal — the backend is the canonical
 * validator, so the frontend schema just enforces enough shape
 * to build a well-typed payload and surface the discriminator
 * for render helpers.
 */

// ── Instruction discriminated union ─────────────────────────────────

const BaseEdgeInstr = z.object({
  source_id: z.string(),
  source_name: z.string(),
  target_id: z.string(),
  target_name: z.string(),
});

const BasePolicyAppInstr = z.object({
  policy_id: z.string(),
  policy_name: z.string(),
  component_id: z.string(),
  component_name: z.string(),
});

export const CreateInstrSchema = z.object({
  instruction_type: z.literal('Create'),
  node_id: z.string(),
  tier: z.enum(['feat', 'resp', 'comp', 'impl']),
  name: z.string(),
  parent_id: z.string().nullable().optional(),
  parent_name: z.string().nullable().optional(),
});
export type CreateInstr = z.infer<typeof CreateInstrSchema>;

export const DeleteInstrSchema = z.object({
  instruction_type: z.literal('Delete'),
  node_id: z.string(),
  name: z.string(),
});
export type DeleteInstr = z.infer<typeof DeleteInstrSchema>;

export const RenameInstrSchema = z.object({
  instruction_type: z.literal('Rename'),
  node_id: z.string(),
  old_name: z.string(),
  new_name: z.string(),
});
export type RenameInstr = z.infer<typeof RenameInstrSchema>;

export const ReassignMappingInstrSchema = z.object({
  instruction_type: z.literal('ReassignMapping'),
  node_id: z.string(),
  name: z.string(),
  new_parent_id: z.string().nullable(),
  new_parent_name: z.string().nullable(),
});
export type ReassignMappingInstr = z.infer<typeof ReassignMappingInstrSchema>;

export const PromoteInstrSchema = z.object({
  instruction_type: z.literal('Promote'),
  node_id: z.string(),
  name: z.string(),
  new_tier: z.enum(['feat', 'resp', 'comp', 'impl']),
});
export type PromoteInstr = z.infer<typeof PromoteInstrSchema>;

export const DemoteInstrSchema = z.object({
  instruction_type: z.literal('Demote'),
  node_id: z.string(),
  name: z.string(),
  new_tier: z.enum(['feat', 'resp', 'comp', 'impl']),
  new_parent_id: z.string().nullable().optional(),
  new_parent_name: z.string().nullable().optional(),
});
export type DemoteInstr = z.infer<typeof DemoteInstrSchema>;

export const MergeInstrSchema = z.object({
  instruction_type: z.literal('Merge'),
  source_ids: z.array(z.string()).min(2),
  source_names: z.array(z.string()).min(2),
  dest_id: z.string(),
  dest_name: z.string(),
});
export type MergeInstr = z.infer<typeof MergeInstrSchema>;

export const SplitInstrSchema = z.object({
  instruction_type: z.literal('Split'),
  source_id: z.string(),
  source_name: z.string(),
  dest_ids: z.array(z.string()).min(2),
  dest_names: z.array(z.string()).min(2),
});
export type SplitInstr = z.infer<typeof SplitInstrSchema>;

export const AddDependencyInstrSchema = BaseEdgeInstr.extend({
  instruction_type: z.literal('AddDependency'),
});
export type AddDependencyInstr = z.infer<typeof AddDependencyInstrSchema>;

export const RemoveDependencyInstrSchema = BaseEdgeInstr.extend({
  instruction_type: z.literal('RemoveDependency'),
});
export type RemoveDependencyInstr = z.infer<typeof RemoveDependencyInstrSchema>;

export const AddDomainParentInstrSchema = BaseEdgeInstr.extend({
  instruction_type: z.literal('AddDomainParent'),
});
export type AddDomainParentInstr = z.infer<typeof AddDomainParentInstrSchema>;

export const RemoveDomainParentInstrSchema = BaseEdgeInstr.extend({
  instruction_type: z.literal('RemoveDomainParent'),
});
export type RemoveDomainParentInstr = z.infer<typeof RemoveDomainParentInstrSchema>;

export const AddPolicyApplicationInstrSchema = BasePolicyAppInstr.extend({
  instruction_type: z.literal('AddPolicyApplication'),
});
export type AddPolicyApplicationInstr = z.infer<typeof AddPolicyApplicationInstrSchema>;

export const RemovePolicyApplicationInstrSchema = BasePolicyAppInstr.extend({
  instruction_type: z.literal('RemovePolicyApplication'),
});
export type RemovePolicyApplicationInstr = z.infer<typeof RemovePolicyApplicationInstrSchema>;

export const AddDecompositionInstrSchema = BaseEdgeInstr.extend({
  instruction_type: z.literal('AddDecomposition'),
});
export type AddDecompositionInstr = z.infer<typeof AddDecompositionInstrSchema>;

export const RemoveDecompositionInstrSchema = BaseEdgeInstr.extend({
  instruction_type: z.literal('RemoveDecomposition'),
});
export type RemoveDecompositionInstr = z.infer<typeof RemoveDecompositionInstrSchema>;

export const InstructionSchema = z.discriminatedUnion('instruction_type', [
  CreateInstrSchema,
  DeleteInstrSchema,
  RenameInstrSchema,
  ReassignMappingInstrSchema,
  PromoteInstrSchema,
  DemoteInstrSchema,
  MergeInstrSchema,
  SplitInstrSchema,
  AddDependencyInstrSchema,
  RemoveDependencyInstrSchema,
  AddDomainParentInstrSchema,
  RemoveDomainParentInstrSchema,
  AddPolicyApplicationInstrSchema,
  RemovePolicyApplicationInstrSchema,
  AddDecompositionInstrSchema,
  RemoveDecompositionInstrSchema,
]);
export type Instruction = z.infer<typeof InstructionSchema>;

// ── Queue row + responses ────────────────────────────────────────────

export const QueueRowSchema = z.object({
  sequence: z.number().int(),
  instruction_type: z.string(),
  payload: z.record(z.string(), z.unknown()),
  status: z.enum(['queued', 'running', 'applied', 'discarded', 'failed']),
  job_id: z.string().nullable(),
  error: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type QueueRow = z.infer<typeof QueueRowSchema>;

export const QueueListResponseSchema = z.object({
  rows: z.array(QueueRowSchema),
});
export type QueueListResponse = z.infer<typeof QueueListResponseSchema>;

export const EnqueueResponseSchema = z.object({ sequence: z.number().int() });
export type EnqueueResponse = z.infer<typeof EnqueueResponseSchema>;

export const DiscardResponseSchema = z.object({ discarded: z.number().int() });
export type DiscardResponse = z.infer<typeof DiscardResponseSchema>;

export const ApplyResponseSchema = z.object({ job_id: z.string().nullable() });
export type ApplyResponse = z.infer<typeof ApplyResponseSchema>;

// ── Fetchers ────────────────────────────────────────────────────────

export async function listQueue(projectId: string): Promise<QueueListResponse> {
  const { data } = await api.get(`/projects/${projectId}/queue`);
  return QueueListResponseSchema.parse(data);
}

export async function enqueueInstruction(
  projectId: string,
  instruction: Instruction,
): Promise<EnqueueResponse> {
  const { data } = await api.post(`/projects/${projectId}/queue/enqueue`, {
    instruction,
  });
  return EnqueueResponseSchema.parse(data);
}

export async function discardPending(
  projectId: string,
  sequence?: number,
): Promise<DiscardResponse> {
  const body = sequence !== undefined ? { sequence } : {};
  const { data } = await api.post(`/projects/${projectId}/queue/discard`, body);
  return DiscardResponseSchema.parse(data);
}

export async function applyQueue(projectId: string): Promise<ApplyResponse> {
  const { data } = await api.post(`/projects/${projectId}/queue/apply`);
  return ApplyResponseSchema.parse(data);
}

// ── Render helper — instruction → prose ─────────────────────────────

/**
 * Render an instruction payload as a short prose line for the queue
 * panel. Mirrors the backend's ``render()`` on each instruction model
 * so the panel reads the same way in both places.
 */
export function renderInstruction(
  type: string,
  payload: Record<string, unknown>,
): string {
  const s = (k: string) => (typeof payload[k] === 'string' ? (payload[k] as string) : '');
  const a = (k: string) => (Array.isArray(payload[k]) ? (payload[k] as string[]) : []);

  switch (type) {
    case 'Create': {
      const parent = s('parent_id')
        ? ` under ${s('parent_name') || s('parent_id')}`
        : '';
      return `Create ${s('tier')} "${s('name')}" (${s('node_id')})${parent}`;
    }
    case 'Delete':
      return `Delete "${s('name')}" (${s('node_id')})`;
    case 'Rename':
      return `Rename ${s('node_id')} from "${s('old_name')}" to "${s('new_name')}"`;
    case 'ReassignMapping': {
      const np = s('new_parent_id');
      if (!np) {
        return `Detach "${s('name')}" (${s('node_id')}) from its current parent`;
      }
      return `Reassign "${s('name')}" (${s('node_id')}) under ${s('new_parent_name') || np}`;
    }
    case 'Promote':
      return `Promote "${s('name')}" (${s('node_id')}) to ${s('new_tier')}`;
    case 'Demote': {
      const parent = s('new_parent_id')
        ? ` under ${s('new_parent_name') || s('new_parent_id')}`
        : '';
      return `Demote "${s('name')}" (${s('node_id')}) to ${s('new_tier')}${parent}`;
    }
    case 'Merge': {
      const names = a('source_names').map((n) => `"${n}"`).join(' and ');
      const ids = a('source_ids').join(', ');
      return `Merge ${names} (${ids}) into "${s('dest_name')}" (${s('dest_id')})`;
    }
    case 'Split': {
      const parts = a('dest_names')
        .map((n, i) => `"${n}" (${a('dest_ids')[i]})`)
        .join(', ');
      return `Split "${s('source_name')}" (${s('source_id')}) into ${parts}`;
    }
    case 'AddDependency':
      return `Add dependency: "${s('source_name')}" → "${s('target_name')}"`;
    case 'RemoveDependency':
      return `Remove dependency: "${s('source_name')}" → "${s('target_name')}"`;
    case 'AddDomainParent':
      return `Set domain parent: "${s('source_name')}" presents "${s('target_name')}"`;
    case 'RemoveDomainParent':
      return `Remove domain parent: "${s('source_name')}" unmapped from "${s('target_name')}"`;
    case 'AddPolicyApplication':
      return `Apply policy "${s('policy_name')}" to "${s('component_name')}"`;
    case 'RemovePolicyApplication':
      return `Detach policy "${s('policy_name')}" from "${s('component_name')}"`;
    case 'AddDecomposition':
      return `Add decomposition: "${s('source_name')}" → "${s('target_name')}"`;
    case 'RemoveDecomposition':
      return `Remove decomposition: "${s('source_name')}" → "${s('target_name')}"`;
    default:
      return `${type} — ${JSON.stringify(payload)}`;
  }
}

/**
 * Return the set of node ids an instruction targets. Mirrors
 * ``affectedNodeIds`` semantics used by the queue tree badge —
 * given a queued row, which sidebar nodes should render the
 * cyan "queued" overlay?
 */
export function affectedNodeIds(
  type: string,
  payload: Record<string, unknown>,
): string[] {
  const out = new Set<string>();
  const add = (k: string) => {
    const v = payload[k];
    if (typeof v === 'string') out.add(v);
  };
  const addArr = (k: string) => {
    const v = payload[k];
    if (Array.isArray(v)) for (const x of v) if (typeof x === 'string') out.add(x);
  };

  switch (type) {
    case 'Create':
    case 'Delete':
    case 'Rename':
    case 'ReassignMapping':
    case 'Promote':
    case 'Demote':
      add('node_id');
      add('parent_id');
      add('new_parent_id');
      break;
    case 'Merge':
      addArr('source_ids');
      add('dest_id');
      break;
    case 'Split':
      add('source_id');
      addArr('dest_ids');
      break;
    case 'AddDependency':
    case 'RemoveDependency':
    case 'AddDomainParent':
    case 'RemoveDomainParent':
    case 'AddDecomposition':
    case 'RemoveDecomposition':
      add('source_id');
      add('target_id');
      break;
    case 'AddPolicyApplication':
    case 'RemovePolicyApplication':
      add('policy_id');
      add('component_id');
      break;
  }
  return Array.from(out);
}

// ── Client-side ID minter ──────────────────────────────────────────
//
// Mirrors ``backend.graph.ids.mint`` — 8 Crockford base32 chars
// appended to the kind prefix. The server validates the format
// on every ``Create`` instruction; collisions are vanishingly
// rare with a 40-bit suffix and the apply handler detects
// ``already exists`` failures at event-apply time, so no
// pre-emptive server round-trip is needed.
const CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

export function mintClientId(kind: 'feat' | 'resp' | 'comp' | 'impl'): string {
  const crypto = globalThis.crypto;
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  let suffix = '';
  for (const b of bytes) suffix += CROCKFORD[b % CROCKFORD.length];
  return `${kind}_${suffix}`;
}
