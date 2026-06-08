import { z } from 'zod';
import api from './client';

// Project references layer (read-only on the dashboard). Refs are
// supplemental documents (DSL specs, deployment runbooks,
// cross-component invariants) whose body lives in the project's
// git repo at `refs/<ref_id>/body.md`. Any node that draws a
// `reference` edge at a ref pulls its content into its regen
// context.
//
// Authoring happens in Claude Code via the `/create_ref` skill;
// the dashboard reads the projected state.

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

export const ReferenceListResponseSchema = z.object({
  references: z.array(ReferenceSummarySchema),
});
export type ReferenceListResponse = z.infer<typeof ReferenceListResponseSchema>;

const ReferenceDetailRawSchema = z.object({
  node: z.object({
    id: z.string(),
    name: z.string(),
    content: z.string(),
    updated_at: z.string(),
  }),
  outgoing_edges: z.array(ReferenceEdgeSchema),
  incoming_edges: z.array(ReferenceEdgeSchema),
});

export type ReferenceDetail = z.infer<typeof ReferenceDetailRawSchema>;

export function makeReferencesApi(projectId: string) {
  return {
    async list(): Promise<ReferenceListResponse> {
      const { data } = await api.get(`/projects/${projectId}/references`);
      return ReferenceListResponseSchema.parse(data);
    },

    async getDetail(refId: string): Promise<ReferenceDetail> {
      const { data } = await api.get(`/projects/${projectId}/references/${refId}`);
      return ReferenceDetailRawSchema.parse(data);
    },
  };
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
