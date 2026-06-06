import { useState } from 'react';
import type { VocabEntry } from '../api/vocabulary';
import { parseVocabEntry } from '../api/vocabulary';
import { useProjectVocabulary } from '../hooks/queries/useVocabularyQueries';
import { PendingVocabularySection } from './PendingVocabularySection';
import { VocabularyEntryDetail } from './VocabularyEntry';

interface Props {
  projectId: string;
}

/**
 * Project vocabulary list view (read-only).
 *
 * Two sections: project-level terms first, then feature-local
 * terms grouped by owning feature. Authoring happens in Claude
 * Code via the `/create_vocab` skill — the dashboard is a
 * projection of the git-resident vocab folder.
 */
export function VocabularyList({ projectId }: Props) {
  const { data, isLoading, error } = useProjectVocabulary(projectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (isLoading) {
    return (
      <div className="p-6 text-gray-400 text-sm">Loading vocabulary…</div>
    );
  }
  if (error) {
    return (
      <div className="p-6 text-red-400 text-sm">
        Failed to load vocabulary.
      </div>
    );
  }
  const entries = data?.entries ?? [];
  const projectEntries = entries.filter((e) => e.parent_id === null);
  const featureEntries = entries.filter((e) => e.parent_id !== null);
  const byFeature = new Map<string, VocabEntry[]>();
  for (const entry of featureEntries) {
    const key = entry.parent_name || entry.parent_id || '(unknown)';
    if (!byFeature.has(key)) byFeature.set(key, []);
    byFeature.get(key)!.push(entry);
  }

  return (
    <div className="flex h-full">
      <div className="w-1/2 overflow-auto border-r border-gray-800 p-4">
        <h2 className="text-sm font-bold text-white mb-4">Vocabulary</h2>

        <PendingVocabularySection projectId={projectId} />

        {entries.length === 0 && (
          <p className="text-sm text-gray-500 italic">
            No vocabulary defined yet. Run{' '}
            <code className="text-gray-300">/create_vocab</code> in
            Claude Code to define project-specific terms that
            downstream generations will always see in context.
          </p>
        )}

        {projectEntries.length > 0 && (
          <section className="mb-6">
            <h3 className="text-xs uppercase tracking-wider text-gray-500 mb-2">
              Project-level ({projectEntries.length})
            </h3>
            <ul className="space-y-1">
              {projectEntries.map((e) => (
                <VocabListItem
                  key={e.id}
                  entry={e}
                  selected={selectedId === e.id}
                  onClick={() => setSelectedId(e.id)}
                />
              ))}
            </ul>
          </section>
        )}

        {byFeature.size > 0 && (
          <section>
            <h3 className="text-xs uppercase tracking-wider text-gray-500 mb-2">
              Feature-local
            </h3>
            {Array.from(byFeature.entries()).map(([featureLabel, items]) => (
              <div key={featureLabel} className="mb-4">
                <div className="text-xs text-gray-400 mb-1">
                  {featureLabel} ({items.length})
                </div>
                <ul className="space-y-1">
                  {items.map((e) => (
                    <VocabListItem
                      key={e.id}
                      entry={e}
                      selected={selectedId === e.id}
                      onClick={() => setSelectedId(e.id)}
                    />
                  ))}
                </ul>
              </div>
            ))}
          </section>
        )}
      </div>

      <div className="w-1/2 overflow-auto p-4">
        {selectedId ? (
          <VocabularyEntryDetail
            entry={entries.find((e) => e.id === selectedId) ?? null}
          />
        ) : (
          <div className="text-sm text-gray-500 italic p-4">
            Select a term to view its definition.
          </div>
        )}
      </div>
    </div>
  );
}

interface VocabListItemProps {
  entry: VocabEntry;
  selected: boolean;
  onClick: () => void;
}

function VocabListItem({ entry, selected, onClick }: VocabListItemProps) {
  const parsed = parseVocabEntry(entry.content);
  const preview = parsed.definition.slice(0, 80);
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className={`w-full text-left px-2 py-1 rounded text-sm ${
          selected
            ? 'bg-blue-900 text-white'
            : 'text-gray-300 hover:bg-gray-800'
        }`}
      >
        <div className="font-mono font-semibold">{entry.name}</div>
        <div className="text-xs text-gray-500 truncate">{preview}</div>
      </button>
    </li>
  );
}
