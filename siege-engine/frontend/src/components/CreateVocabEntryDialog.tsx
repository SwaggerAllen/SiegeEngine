import { useState } from 'react';
import { buildVocabEntryXml } from '../api/vocabulary';
import { useCreateVocabMutation } from '../hooks/mutations/useVocabularyMutations';
import { useFeatures } from '../hooks/queries/useFeatureQueries';

interface Props {
  projectId: string;
  initialScope?: 'project' | 'feature';
  onClose: () => void;
}

/**
 * Modal dialog for creating a new vocab entry directly, without
 * running an LLM flow. The user picks scope (project-level or
 * feature-local), enters a name, definition, optional
 * disambiguation, and optional see-also references, and hits
 * create. The frontend builds the <vocab-entry> XML block via
 * ``buildVocabEntryXml`` and submits it through the create
 * mutation; the server re-validates it on receipt.
 */
export function CreateVocabEntryDialog({
  projectId,
  initialScope = 'project',
  onClose,
}: Props) {
  const [name, setName] = useState('');
  const [scope, setScope] = useState<'project' | 'feature'>(initialScope);
  const [featureId, setFeatureId] = useState<string>('');
  const [definition, setDefinition] = useState('');
  const [disambiguation, setDisambiguation] = useState('');
  const [seeAlsoText, setSeeAlsoText] = useState('');

  const createMutation = useCreateVocabMutation(projectId);
  const featuresQuery = useFeatures(projectId);
  const features = featuresQuery.data?.features ?? [];

  const canSubmit =
    name.trim().length > 0 &&
    definition.trim().length > 0 &&
    (scope === 'project' || featureId !== '');

  const handleSubmit = () => {
    const seeAlsoNames = seeAlsoText
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    const content = buildVocabEntryXml(
      definition.trim(),
      disambiguation.trim() || null,
      seeAlsoNames
    );
    createMutation.mutate(
      {
        name: name.trim(),
        content,
        parentId: scope === 'feature' ? featureId : null,
      },
      { onSuccess: () => onClose() }
    );
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      role="dialog"
      aria-label="Create vocab entry"
    >
      <div className="bg-gray-900 border border-gray-700 rounded p-6 w-full max-w-lg space-y-4">
        <h2 className="text-sm font-bold text-white">Add vocabulary term</h2>

        <label className="block space-y-1">
          <div className="text-xs uppercase tracking-wider text-gray-400">
            Term name
          </div>
          <input
            type="text"
            className="w-full px-2 py-1 bg-gray-950 border border-gray-700 rounded text-sm text-gray-100 font-mono"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. boulder, tranche"
          />
        </label>

        <fieldset className="space-y-2">
          <legend className="text-xs uppercase tracking-wider text-gray-400">
            Scope
          </legend>
          <label className="flex items-center gap-2 text-sm text-gray-200">
            <input
              type="radio"
              checked={scope === 'project'}
              onChange={() => setScope('project')}
            />
            Project-level (visible to every regen in every tier)
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-200">
            <input
              type="radio"
              checked={scope === 'feature'}
              onChange={() => setScope('feature')}
            />
            Feature-local (only visible when a regen reaches this
            feature's subtree)
          </label>
          {scope === 'feature' && (
            <select
              className="w-full px-2 py-1 bg-gray-950 border border-gray-700 rounded text-sm text-gray-100"
              value={featureId}
              onChange={(e) => setFeatureId(e.target.value)}
            >
              <option value="">Select a feature…</option>
              {features.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          )}
        </fieldset>

        <label className="block space-y-1">
          <div className="text-xs uppercase tracking-wider text-gray-400">
            Definition
          </div>
          <textarea
            className="w-full px-2 py-1 bg-gray-950 border border-gray-700 rounded text-sm text-gray-100"
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
            className="w-full px-2 py-1 bg-gray-950 border border-gray-700 rounded text-sm text-gray-100"
            rows={2}
            value={disambiguation}
            onChange={(e) => setDisambiguation(e.target.value)}
            placeholder="Not to be confused with..."
          />
        </label>

        <label className="block space-y-1">
          <div className="text-xs uppercase tracking-wider text-gray-400">
            See also (comma-separated term names, optional)
          </div>
          <input
            type="text"
            className="w-full px-2 py-1 bg-gray-950 border border-gray-700 rounded text-sm text-gray-100"
            value={seeAlsoText}
            onChange={(e) => setSeeAlsoText(e.target.value)}
            placeholder="term1, term2"
          />
        </label>

        {createMutation.isError && (
          <div className="text-xs text-red-400">
            {String(createMutation.error ?? 'Create failed')}
          </div>
        )}

        <div className="flex gap-2 justify-end">
          <button
            type="button"
            className="text-xs px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-white"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!canSubmit || createMutation.isPending}
            className="text-xs px-3 py-1 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 rounded text-white"
            onClick={handleSubmit}
          >
            {createMutation.isPending ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}
