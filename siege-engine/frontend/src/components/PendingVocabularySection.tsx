import { useExpansion } from '../hooks/queries/useExpansionQueries';
import {
  parsePendingVocabulary,
  type PendingVocabEntry,
} from '../lib/parsePendingVocabulary';

/**
 * Read-only peek at vocabulary entries living inside an
 * unapproved feature-expansion draft.
 *
 * The minted ``vocab_*`` projection only lands after the user
 * approves the draft, which previously meant the Vocabulary
 * page stayed empty while the user was trying to decide whether
 * to approve. This section parses the pending ``<vocabulary>``
 * block straight out of the draft's XML and renders each
 * ``<term>`` as a simple card so the user can review what
 * approval will mint.
 *
 * Renders nothing when there's no pending draft or no vocabulary
 * block inside it.
 */

export function PendingVocabularySection({ projectId }: { projectId: string }) {
  const { data } = useExpansion(projectId);
  const pendingXml = data?.pending_draft?.content ?? null;
  const entries = parsePendingVocabulary(pendingXml);
  if (entries.length === 0) return null;

  const projectEntries = entries.filter((e) => e.scope === 'project');
  const featureEntries = entries.filter((e) => e.scope === 'feature');

  return (
    <section
      className="mb-6 rounded border border-amber-800/60 bg-amber-950/20 p-3"
      aria-label="Pending vocabulary (unapproved)"
    >
      <div className="flex items-baseline justify-between mb-2">
        <h3 className="text-xs uppercase tracking-wider text-amber-300">
          Pending vocabulary ({entries.length})
        </h3>
        <span className="text-[10px] text-amber-400/80 italic">
          From the pending expansion draft — not yet minted.
        </span>
      </div>
      <p className="text-xs text-gray-400 mb-3">
        Terms the LLM proposed in the current feature-expansion draft.
        These mint as real vocabulary entries when you approve the
        draft; until then they&apos;re read-only.
      </p>
      {projectEntries.length > 0 && (
        <PendingGroup label="Project-level" entries={projectEntries} />
      )}
      {featureEntries.length > 0 && (
        <PendingGroup
          label="Feature-local"
          entries={featureEntries}
          showFeature
        />
      )}
    </section>
  );
}

function PendingGroup({
  label,
  entries,
  showFeature = false,
}: {
  label: string;
  entries: PendingVocabEntry[];
  showFeature?: boolean;
}) {
  return (
    <div className="mb-3">
      <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-1">
        {label}
      </div>
      <ul className="space-y-2">
        {entries.map((e) => (
          <li
            key={`${e.scope}:${e.featureName ?? ''}:${e.name}`}
            className="rounded border border-gray-800 bg-gray-900 p-2"
          >
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-sm text-gray-100">{e.name}</span>
              {showFeature && e.featureName && (
                <span className="text-[10px] text-gray-500">
                  in {e.featureName}
                </span>
              )}
            </div>
            <p className="text-sm text-gray-300 mt-1 whitespace-pre-wrap">
              {e.definition}
            </p>
            {e.disambiguation && (
              <p className="text-xs text-gray-400 italic mt-1">
                Not to be confused with: {e.disambiguation}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
