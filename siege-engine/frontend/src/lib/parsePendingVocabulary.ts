/**
 * Extract vocabulary entries from a pending feature-expansion
 * draft's raw XML. Best-effort DOMParser walk — the backend
 * validator is authoritative; this is a read-only preview shown
 * on the Vocabulary page before the draft is approved so the
 * user can see what will mint.
 */

export interface PendingVocabEntry {
  name: string;
  scope: string;
  featureName: string | null;
  definition: string;
  disambiguation: string | null;
}

const VOCAB_BLOCK_RE = /<vocabulary[\s\S]*?<\/vocabulary>/i;

export function parsePendingVocabulary(
  xml: string | null | undefined,
): PendingVocabEntry[] {
  if (!xml) return [];
  const match = VOCAB_BLOCK_RE.exec(xml);
  if (!match) return [];
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(
      `<root>${match[0]}</root>`,
      'text/html',
    );
  } catch {
    return [];
  }
  const entries: PendingVocabEntry[] = [];
  doc.querySelectorAll('vocabulary > term').forEach((termEl) => {
    const name = termEl.getAttribute('name') ?? '';
    const scope = termEl.getAttribute('scope') ?? '';
    const featureName = termEl.getAttribute('feature-name');
    const definition =
      termEl.querySelector('vocab-entry > definition')?.textContent?.trim() ?? '';
    const disambiguation =
      termEl.querySelector('vocab-entry > disambiguation')?.textContent?.trim() ??
      null;
    if (!name || !definition) return;
    entries.push({
      name,
      scope,
      featureName,
      definition,
      disambiguation: disambiguation && disambiguation.length > 0 ? disambiguation : null,
    });
  });
  return entries;
}
