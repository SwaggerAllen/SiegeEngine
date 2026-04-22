import { z } from 'zod';
import api from './client';
import type { BootstrapResponse, GenerationStatus, TelemetrySummary } from './bootstrapApi';
import { makeBootstrapApi } from './bootstrapApi';

// Phase 6.6: project references layer. Refs are first-class
// supplemental documents (DSL specs, deployment runbooks,
// cross-component invariants) that any other node can pull
// into its regen context via an outgoing `reference` edge.
//
// Lifecycle ops (get state, feedback, approve, discard, cancel)
// reuse the standard bootstrap-tier API the other tiers share.
// The list / create / delete / edge endpoints are ref-specific
// and live alongside.

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

export const CreateReferenceResponseSchema = z.object({
  ref_id: z.string(),
  job_id: z.string(),
});
export type CreateReferenceResponse = z.infer<typeof CreateReferenceResponseSchema>;

// Detail wraps the standard bootstrap response shape (node /
// pending_draft / generation_status / etc.) and adds the
// ref-specific edge lists.
export interface ReferenceDetail extends BootstrapResponse {
  outgoing_edges: ReferenceEdge[];
  incoming_edges: ReferenceEdge[];
}

const ReferenceDetailRawSchema = z.object({
  node: z.object({
    id: z.string(),
    name: z.string(),
    content: z.string(),
    updated_at: z.string(),
  }),
  pending_draft: z
    .object({
      id: z.string(),
      content: z.string(),
      created_at: z.string(),
    })
    .nullable(),
  previous_draft_content: z.string().nullish().transform((v) => v ?? null),
  auto_revision_intermediates: z
    .array(
      z.object({
        label: z.string(),
        content: z.string(),
        auto_revision_pass: z.number().int(),
      }),
    )
    .default([]),
  generation_status: z.enum(['idle', 'running', 'failed']),
  last_error: z.string().nullable(),
  latest_telemetry: z
    .object({
      prompt_tokens: z.number(),
      completion_tokens: z.number(),
      model: z.string(),
      created_at: z.string(),
    })
    .nullable(),
  generation_started_at: z.string().nullish().transform((v) => v ?? null),
  current_attempt: z.number().int().nullish().transform((v) => v ?? null),
  max_attempts: z.number().int().nullish().transform((v) => v ?? null),
  failed_raw_output: z.string().nullish().transform((v) => v ?? null),
  review_text: z.string().default(''),
  review_status: z.enum(['idle', 'running', 'failed']).default('idle'),
  review_last_error: z.string().nullish().transform((v) => v ?? null),
  review_started_at: z.string().nullish().transform((v) => v ?? null),
  review_current_attempt: z.number().int().nullish().transform((v) => v ?? null),
  review_max_attempts: z.number().int().nullish().transform((v) => v ?? null),
  is_stale: z.boolean().default(false),
  staleness_reasons: z.array(z.string()).default([]),
  outgoing_edges: z.array(ReferenceEdgeSchema),
  incoming_edges: z.array(ReferenceEdgeSchema),
});

// Standard bootstrap-pattern lifecycle handlers, scoped per ref.
// `referencesApi.getState(refId)` etc. The base URL closure pulls
// `projectId` from the per-call context, but since refs are owned
// per-project we curry it via the `projectScopedReferencesApi`
// factory below so call sites only pass `refId`.
export function makeReferencesApi(projectId: string) {
  const lifecycle = makeBootstrapApi(
    (refId) => `/projects/${projectId}/references/${refId}`,
  );

  return {
    ...lifecycle,

    async list(): Promise<ReferenceListResponse> {
      const { data } = await api.get(`/projects/${projectId}/references`);
      return ReferenceListResponseSchema.parse(data);
    },

    async getDetail(refId: string): Promise<ReferenceDetail> {
      const { data } = await api.get(`/projects/${projectId}/references/${refId}`);
      return ReferenceDetailRawSchema.parse(data);
    },

    async create(
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
    },

    async delete(refId: string): Promise<void> {
      await api.post(`/projects/${projectId}/references/${refId}/delete`);
    },

    async addEdge(sourceId: string, targetId: string): Promise<ReferenceEdge> {
      const { data } = await api.post(`/projects/${projectId}/edges/reference`, {
        source_id: sourceId,
        target_id: targetId,
      });
      return ReferenceEdgeSchema.parse(data);
    },

    async removeEdge(sourceId: string, targetId: string): Promise<void> {
      await api.delete(`/projects/${projectId}/edges/reference`, {
        data: { source_id: sourceId, target_id: targetId },
      });
    },
  };
}

// Re-exported for the panel — keeps the import surface narrow
// since most consumers only want the detail shape and the helper
// types.
export type { GenerationStatus, TelemetrySummary };

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
// fields (used by the create-route's seed shell on the backend
// and by the small XML round-trip tests on the frontend).
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
