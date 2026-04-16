import { z } from 'zod';
import api from './client';

// Phase 6.6: project references layer. Refs are first-class
// supplemental documents (DSL specs, deployment runbooks,
// cross-component invariants) that any other node can pull
// into its regen context via an outgoing `reference` edge.
// Content is raw `<reference>` XML on the server; the frontend
// submits user-supplied seed descriptions and iterates via the
// LLM draft lifecycle, not direct content edits.
//
// Unlike vocab (direct-CRUD), refs use the expansion-style
// four-state flow: pending draft → feedback → approve. Unlike
// other bootstrap tiers, refs are NOT frozen after approval —
// `UpdateReference` re-enters draft state regardless.

export const ReferenceEdgeSchema = z.object({
  edge_id: z.string(),
  source_id: z.string(),
  target_id: z.string(),
});
export type ReferenceEdge = z.infer<typeof ReferenceEdgeSchema>;

export const ReferenceSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  has_content: z.boolean(),
  updated_at: z.string(),
});
export type ReferenceSummary = z.infer<typeof ReferenceSummarySchema>;

export const ReferenceDraftSchema = z.object({
  id: z.string(),
  content: z.string(),
  created_at: z.string(),
});
export type ReferenceDraft = z.infer<typeof ReferenceDraftSchema>;

export const TelemetrySummarySchema = z.object({
  prompt_tokens: z.number(),
  completion_tokens: z.number(),
  model: z.string(),
  created_at: z.string(),
});
export type TelemetrySummary = z.infer<typeof TelemetrySummarySchema>;

export const ReferenceDetailSchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  updated_at: z.string(),
  pending_draft: ReferenceDraftSchema.nullable(),
  generation_status: z.enum(['idle', 'running', 'failed']),
  last_error: z.string().nullable(),
  latest_telemetry: TelemetrySummarySchema.nullable(),
  generation_started_at: z.string().nullable(),
  outgoing_edges: z.array(ReferenceEdgeSchema),
  incoming_edges: z.array(ReferenceEdgeSchema),
});
export type ReferenceDetail = z.infer<typeof ReferenceDetailSchema>;

export const ReferenceListResponseSchema = z.object({
  references: z.array(ReferenceSummarySchema),
});
export type ReferenceListResponse = z.infer<typeof ReferenceListResponseSchema>;

export const CreateReferenceResponseSchema = z.object({
  ref_id: z.string(),
  job_id: z.string(),
});
export type CreateReferenceResponse = z.infer<typeof CreateReferenceResponseSchema>;

export async function getReferences(projectId: string): Promise<ReferenceListResponse> {
  const { data } = await api.get(`/projects/${projectId}/references`);
  return ReferenceListResponseSchema.parse(data);
}

export async function getReference(
  projectId: string,
  refId: string,
): Promise<ReferenceDetail> {
  const { data } = await api.get(`/projects/${projectId}/references/${refId}`);
  return ReferenceDetailSchema.parse(data);
}

export async function createReference(
  projectId: string,
  name: string,
  seedDescription: string,
  relatedNodes: string[],
): Promise<CreateReferenceResponse> {
  const { data } = await api.post(`/projects/${projectId}/references/create`, {
    name,
    seed_description: seedDescription,
    related_nodes: relatedNodes,
  });
  return CreateReferenceResponseSchema.parse(data);
}

export async function updateReference(
  projectId: string,
  refId: string,
  feedback: string | null,
): Promise<{ job_id: string }> {
  const { data } = await api.post(
    `/projects/${projectId}/references/${refId}/feedback`,
    { feedback },
  );
  return { job_id: data.job_id };
}

export async function approveReferenceDraft(
  projectId: string,
  refId: string,
  draftId: string,
): Promise<void> {
  await api.post(`/projects/${projectId}/references/${refId}/approve`, {
    draft_id: draftId,
  });
}

export async function discardReferenceDraft(
  projectId: string,
  refId: string,
  draftId: string,
): Promise<void> {
  await api.post(`/projects/${projectId}/references/${refId}/discard`, {
    draft_id: draftId,
  });
}

export async function deleteReference(
  projectId: string,
  refId: string,
): Promise<void> {
  await api.post(`/projects/${projectId}/references/${refId}/delete`);
}

export async function addReferenceEdge(
  projectId: string,
  sourceId: string,
  targetId: string,
): Promise<ReferenceEdge> {
  const { data } = await api.post(`/projects/${projectId}/edges/reference`, {
    source_id: sourceId,
    target_id: targetId,
  });
  return ReferenceEdgeSchema.parse(data);
}

export async function removeReferenceEdge(
  projectId: string,
  sourceId: string,
  targetId: string,
): Promise<void> {
  await api.delete(`/projects/${projectId}/edges/reference`, {
    data: { source_id: sourceId, target_id: targetId },
  });
}

// Parse a stored `<reference>` XML block into structured fields
// for display. Server-validated content; client-side extraction
// is regex-based to match the minimal parser used by vocab.
export interface ParsedReference {
  title: string;
  body: string;
  seeAlsoIds: string[];
}

export function parseReference(content: string): ParsedReference {
  const title = extractTagText(content, 'title') ?? '';
  const body = extractTagText(content, 'body') ?? '';
  const seeAlsoIds = extractSeeAlsoIds(content);
  return { title, body, seeAlsoIds };
}

// Build a canonical `<reference>` XML block from structured
// fields (used by potential future direct-edit paths;
// currently the LLM generates these).
export function buildReferenceXml(
  title: string,
  body: string,
  seeAlsoIds: string[] = [],
): string {
  const parts: string[] = ['<reference>'];
  parts.push(`<title>${escapeXml(title)}</title>`);
  parts.push(`<body>${escapeXml(body)}</body>`);
  if (seeAlsoIds.length > 0) {
    parts.push('<see-also>');
    for (const id of seeAlsoIds) {
      parts.push(`<ref to="${escapeAttr(id)}"/>`);
    }
    parts.push('</see-also>');
  }
  parts.push('</reference>');
  return parts.join('');
}

function escapeXml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function escapeAttr(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}

function extractTagText(xml: string, tag: string): string | null {
  const match = xml.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`));
  if (!match) return null;
  return unescapeXml(match[1].trim());
}

function extractSeeAlsoIds(xml: string): string[] {
  const block = xml.match(/<see-also>([\s\S]*?)<\/see-also>/);
  if (!block) return [];
  const ids: string[] = [];
  const refRe = /<ref\s+to="([^"]*)"/g;
  let m: RegExpExecArray | null;
  while ((m = refRe.exec(block[1])) !== null) {
    ids.push(m[1]);
  }
  return ids;
}

function unescapeXml(text: string): string {
  return text.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
}
