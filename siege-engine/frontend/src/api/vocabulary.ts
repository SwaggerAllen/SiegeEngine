import { z } from 'zod';
import api from './client';

// Phase 5.5: project vocabulary layer. Vocab entries are a
// first-class node tier scoped via parent_id — null for
// project-level, a feat_* id for feature-local. Content is
// raw <vocab-entry> XML on the server; the frontend renders
// it with light structure extraction for display, and submits
// user edits as raw XML blocks the server re-validates.

export const VocabEntrySchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  parent_id: z.string().nullable(),
  parent_name: z.string().nullable(),
  updated_at: z.string(),
});
export type VocabEntry = z.infer<typeof VocabEntrySchema>;

export const VocabListResponseSchema = z.object({
  entries: z.array(VocabEntrySchema),
});
export type VocabListResponse = z.infer<typeof VocabListResponseSchema>;

export async function getVocabulary(
  projectId: string
): Promise<VocabListResponse> {
  const { data } = await api.get(`/projects/${projectId}/vocabulary`);
  return VocabListResponseSchema.parse(data);
}

export async function getFeatureVocabulary(
  projectId: string,
  featId: string
): Promise<VocabListResponse> {
  const { data } = await api.get(
    `/projects/${projectId}/features/${featId}/vocabulary`
  );
  return VocabListResponseSchema.parse(data);
}

export async function getVocabularyEntry(
  projectId: string,
  vocabId: string
): Promise<VocabEntry> {
  const { data } = await api.get(
    `/projects/${projectId}/vocabulary/${vocabId}`
  );
  return VocabEntrySchema.parse(data);
}

export async function createVocabEntry(
  projectId: string,
  name: string,
  content: string,
  parentId: string | null
): Promise<VocabEntry> {
  const { data } = await api.post(
    `/projects/${projectId}/vocabulary/create`,
    { name, content, parent_id: parentId }
  );
  return VocabEntrySchema.parse(data);
}

export async function editVocabEntry(
  projectId: string,
  vocabId: string,
  newContent: string
): Promise<VocabEntry> {
  const { data } = await api.post(
    `/projects/${projectId}/vocabulary/${vocabId}/edit`,
    { new_content: newContent }
  );
  return VocabEntrySchema.parse(data);
}

export async function renameVocabEntry(
  projectId: string,
  vocabId: string,
  newName: string
): Promise<VocabEntry> {
  const { data } = await api.post(
    `/projects/${projectId}/vocabulary/${vocabId}/rename`,
    { new_name: newName }
  );
  return VocabEntrySchema.parse(data);
}

export async function reparentVocabEntry(
  projectId: string,
  vocabId: string,
  newParentId: string | null
): Promise<VocabEntry> {
  const { data } = await api.post(
    `/projects/${projectId}/vocabulary/${vocabId}/reparent`,
    { new_parent_id: newParentId }
  );
  return VocabEntrySchema.parse(data);
}

export async function deleteVocabEntry(
  projectId: string,
  vocabId: string
): Promise<void> {
  await api.post(`/projects/${projectId}/vocabulary/${vocabId}/delete`);
}

// Build a canonical <vocab-entry> XML block from the three
// structured fields the creation/edit form collects. The
// server re-parses and re-validates this; the frontend's role
// is just to construct well-formed XML so the validator
// accepts it without the user having to hand-write markup.
export function buildVocabEntryXml(
  definition: string,
  disambiguation: string | null,
  seeAlsoNames: string[]
): string {
  const parts: string[] = ['<vocab-entry>'];
  parts.push(`<definition>${escapeXml(definition)}</definition>`);
  if (disambiguation && disambiguation.trim()) {
    parts.push(
      `<disambiguation>${escapeXml(disambiguation)}</disambiguation>`
    );
  }
  if (seeAlsoNames.length > 0) {
    parts.push('<see-also>');
    for (const name of seeAlsoNames) {
      parts.push(`<ref name="${escapeAttr(name)}"/>`);
    }
    parts.push('</see-also>');
  }
  parts.push('</vocab-entry>');
  return parts.join('');
}

function escapeXml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function escapeAttr(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}

// Parse a stored <vocab-entry> XML block into its three
// conventional fields for display. Uses a minimal regex-based
// extractor rather than a full XML parser because the server
// already validated the content and we only need to pull out
// text inside known tags.
export interface ParsedVocabEntry {
  definition: string;
  disambiguation: string | null;
  seeAlsoNames: string[];
}

export function parseVocabEntry(content: string): ParsedVocabEntry {
  const definition =
    extractTagText(content, 'definition') ?? content.trim();
  const disambiguation = extractTagText(content, 'disambiguation');
  const seeAlsoNames = extractSeeAlsoNames(content);
  return { definition, disambiguation, seeAlsoNames };
}

function extractTagText(xml: string, tag: string): string | null {
  const match = xml.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`));
  if (!match) return null;
  return unescapeXml(match[1].trim());
}

function extractSeeAlsoNames(xml: string): string[] {
  const block = xml.match(/<see-also>([\s\S]*?)<\/see-also>/);
  if (!block) return [];
  const names: string[] = [];
  const refRe = /<ref\s+name="([^"]*)"/g;
  let m: RegExpExecArray | null;
  while ((m = refRe.exec(block[1])) !== null) {
    names.push(m[1]);
  }
  return names;
}

function unescapeXml(text: string): string {
  return text
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}
