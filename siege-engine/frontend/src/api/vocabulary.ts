import { z } from 'zod';
import api from './client';

// Project vocabulary layer (read-only on the dashboard). Vocab
// entries' bodies live in the project repo at
// `vocab/<vocab_id>/body.md`; the dashboard reads the projected
// state via the v3 endpoints. Authoring happens in Claude Code
// via the `/create_vocab` skill.

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
