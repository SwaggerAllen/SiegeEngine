import type { VocabEntry } from '../api/vocabulary';
import { parseVocabEntry } from '../api/vocabulary';

interface Props {
  entry: VocabEntry | null;
}

/**
 * Read-only detail view for a single vocab entry.
 *
 * Authoring happens via the `/create_vocab` Claude Code skill —
 * the dashboard shows the projected state. To edit a term, change
 * the body file in the project repo.
 */
export function VocabularyEntryDetail({ entry }: Props) {
  if (entry === null) {
    return (
      <div className="text-sm text-gray-500 italic">
        Entry not found.
      </div>
    );
  }

  const parsed = parseVocabEntry(entry.content);

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-bold text-white font-mono">
        {entry.name}
      </h2>

      <div className="text-xs text-gray-500">
        {entry.parent_id === null
          ? 'Project-level'
          : `From feature: ${entry.parent_name || entry.parent_id}`}
      </div>

      <section className="space-y-2">
        <h3 className="text-xs uppercase tracking-wider text-gray-400">
          Definition
        </h3>
        <p className="text-sm text-gray-300 whitespace-pre-wrap m-0">
          {parsed.definition}
        </p>
      </section>

      {parsed.disambiguation && (
        <section className="space-y-2 border-l-2 border-yellow-700 pl-3">
          <h3 className="text-xs uppercase tracking-wider text-yellow-500">
            ⚠ Not to be confused with
          </h3>
          <p className="text-sm text-yellow-200 whitespace-pre-wrap m-0">
            {parsed.disambiguation}
          </p>
        </section>
      )}

      {parsed.seeAlsoNames.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-xs uppercase tracking-wider text-gray-400">
            See also
          </h3>
          <ul className="text-xs font-mono text-gray-400 space-y-0.5 m-0 pl-0 list-none">
            {parsed.seeAlsoNames.map((name) => (
              <li key={name}>
                <span className="text-gray-500">→ </span>
                <span className="text-blue-300">{name}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="text-xs text-gray-500 italic border-t border-gray-800 pt-3">
        Vocabulary is authored in Claude Code via the{' '}
        <code className="text-gray-300">/create_vocab</code> skill.
      </section>
    </div>
  );
}
