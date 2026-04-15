import { useState } from 'react';
import type { VocabEntry } from '../api/vocabulary';
import { buildVocabEntryXml, parseVocabEntry } from '../api/vocabulary';
import { useEditVocabMutation } from '../hooks/mutations/useVocabularyMutations';

interface Props {
  projectId: string;
  entry: VocabEntry | null;
  onDelete: () => void;
}

/**
 * Detail view for a single vocab entry. Shows the three
 * structured fields (definition, disambiguation, see-also)
 * extracted from the stored <vocab-entry> XML, with edit /
 * delete actions. Editing is a direct content replace — no
 * LLM involvement, no draft lifecycle at this stage.
 *
 * The XML-aware renderer (using the existing comparch
 * renderer map) is a polish pass for a follow-up; for now
 * the detail view pulls fields out via the
 * ``parseVocabEntry`` helper in the API module and renders
 * them with plain styled sections.
 */
export function VocabularyEntryDetail({
  projectId,
  entry,
  onDelete,
}: Props) {
  const [editing, setEditing] = useState(false);
  const editMutation = useEditVocabMutation(projectId);

  if (entry === null) {
    return (
      <div className="text-sm text-gray-500 italic">
        Entry not found.
      </div>
    );
  }

  const parsed = parseVocabEntry(entry.content);

  if (editing) {
    return (
      <VocabEntryEditor
        initialDefinition={parsed.definition}
        initialDisambiguation={parsed.disambiguation}
        initialSeeAlso={parsed.seeAlsoNames}
        onCancel={() => setEditing(false)}
        onSave={(newContent) => {
          editMutation.mutate(
            { vocabId: entry.id, newContent },
            { onSuccess: () => setEditing(false) }
          );
        }}
        saving={editMutation.isPending}
        error={
          editMutation.isError
            ? String(editMutation.error ?? 'Edit failed')
            : null
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-white font-mono">
          {entry.name}
        </h2>
        <div className="flex gap-2">
          <button
            type="button"
            className="text-xs px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-white"
            onClick={() => setEditing(true)}
          >
            Edit
          </button>
          <button
            type="button"
            className="text-xs px-3 py-1 bg-red-900 hover:bg-red-800 rounded text-white"
            onClick={onDelete}
          >
            Delete
          </button>
        </div>
      </div>

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
    </div>
  );
}

interface EditorProps {
  initialDefinition: string;
  initialDisambiguation: string | null;
  initialSeeAlso: string[];
  onCancel: () => void;
  onSave: (newContent: string) => void;
  saving: boolean;
  error: string | null;
}

function VocabEntryEditor({
  initialDefinition,
  initialDisambiguation,
  initialSeeAlso,
  onCancel,
  onSave,
  saving,
  error,
}: EditorProps) {
  const [definition, setDefinition] = useState(initialDefinition);
  const [disambiguation, setDisambiguation] = useState(
    initialDisambiguation ?? ''
  );
  const [seeAlsoText, setSeeAlsoText] = useState(initialSeeAlso.join(', '));

  const handleSave = () => {
    const seeAlsoNames = seeAlsoText
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    const content = buildVocabEntryXml(
      definition.trim(),
      disambiguation.trim() || null,
      seeAlsoNames
    );
    onSave(content);
  };

  return (
    <div className="space-y-4">
      <h2 className="text-sm font-bold text-white">Edit vocab entry</h2>

      <label className="block space-y-1">
        <div className="text-xs uppercase tracking-wider text-gray-400">
          Definition
        </div>
        <textarea
          className="w-full px-2 py-1 bg-gray-900 border border-gray-700 rounded text-sm text-gray-100"
          rows={4}
          value={definition}
          onChange={(e) => setDefinition(e.target.value)}
        />
      </label>

      <label className="block space-y-1">
        <div className="text-xs uppercase tracking-wider text-gray-400">
          Disambiguation (optional)
        </div>
        <textarea
          className="w-full px-2 py-1 bg-gray-900 border border-gray-700 rounded text-sm text-gray-100"
          rows={3}
          value={disambiguation}
          onChange={(e) => setDisambiguation(e.target.value)}
          placeholder="Not to be confused with..."
        />
      </label>

      <label className="block space-y-1">
        <div className="text-xs uppercase tracking-wider text-gray-400">
          See also (comma-separated term names)
        </div>
        <input
          type="text"
          className="w-full px-2 py-1 bg-gray-900 border border-gray-700 rounded text-sm text-gray-100"
          value={seeAlsoText}
          onChange={(e) => setSeeAlsoText(e.target.value)}
          placeholder="term1, term2"
        />
      </label>

      {error && <div className="text-xs text-red-400">{error}</div>}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={saving || definition.trim().length === 0}
          className="text-xs px-3 py-1 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 rounded text-white"
          onClick={handleSave}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          className="text-xs px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-white"
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
