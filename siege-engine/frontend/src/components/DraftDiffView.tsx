import { useMemo, useState } from 'react';
import { Diff, Hunk, parseDiff } from 'react-diff-view';
import type { HunkData, ViewType } from 'react-diff-view';
import { diffAsText } from 'unidiff';

interface Props {
  /**
   * The "before" content. Typically the most recently discarded
   * draft's content (across Reject & Regenerate cycles), falling
   * back to the approved node's content on the first regen after
   * approval. ``null`` / empty means "no prior version available"
   * and the component renders a hint instead of a diff.
   */
  before: string | null;
  /** The current pending draft's content. */
  after: string;
  /**
   * Optional caption shown above the diff, typically describing
   * what the "before" side represents (e.g. "Comparing against
   * the previous draft" or "Comparing against the approved
   * content"). Rendered in small italic text.
   */
  label?: string;
  /**
   * Phase 13 — the generator's self-report of what this draft
   * changed / contains. Lifted out of the ``<change-summary>``
   * tag at persist time; ``null``/empty for pre-Phase-13 drafts
   * and fan-in drafts. Rendered as a small callout above the
   * layout toggle so reviewers get the "why" before reading the
   * "what" diff below.
   */
  summaryText?: string | null;
}

/**
 * Side-by-side / unified diff view for a bootstrap-tier draft.
 *
 * Feeds the before+after strings through ``unidiff`` to produce a
 * unified diff, then renders it with ``react-diff-view``. Two
 * render modes toggle between a split layout (left = before,
 * right = after) and a unified layout (additions/deletions
 * interleaved).
 *
 * The library's default light palette is overridden via CSS
 * variables scoped to ``.diff-view-dark`` — see
 * ``frontend/src/index.css``. Consumers mount the component
 * directly; all the dark-theme work is contained.
 */
export function DraftDiffView({ before, after, label, summaryText }: Props) {
  const [viewType, setViewType] = useState<ViewType>('split');

  const beforeText = (before ?? '').trim();
  const afterText = (after ?? '').trim();
  const trimmedSummary = (summaryText ?? '').trim();

  const { hasPrevious, hasChanges, hunks } = useMemo(() => {
    if (before === null) {
      return { hasPrevious: false, hasChanges: false, hunks: [] as HunkData[] };
    }
    const unified = diffAsText(beforeText, afterText, { context: 3 });
    if (!unified) {
      return { hasPrevious: true, hasChanges: false, hunks: [] as HunkData[] };
    }
    // Give parseDiff a minimal valid unified-diff envelope (with
    // `diff --git` headers) so downstream consumers of parsed
    // FileData can render a single file of `modify` type. The
    // `a/` / `b/` prefixes are arbitrary labels; react-diff-view
    // only uses them for gutters, not filesystem resolution.
    const envelope = `diff --git a/before b/after\n${unified}`;
    const files = parseDiff(envelope, { nearbySequences: 'zip' });
    const parsedHunks = files[0]?.hunks ?? [];
    return { hasPrevious: true, hasChanges: parsedHunks.length > 0, hunks: parsedHunks };
  }, [before, beforeText, afterText]);

  const summaryCallout = trimmedSummary ? (
    <div
      className="rounded border-l-2 border-blue-700/80 bg-gray-900/50 px-3 py-2 text-sm italic text-gray-200"
      data-testid="draft-diff-summary"
    >
      {trimmedSummary}
    </div>
  ) : null;

  if (!hasPrevious) {
    return (
      <div className="space-y-2">
        {summaryCallout}
        <div className="p-4 border border-gray-800 rounded text-xs text-gray-500 italic bg-gray-900/40">
          No prior draft or approved content to diff against — this is
          the first version on this tier.
        </div>
      </div>
    );
  }

  if (!hasChanges) {
    return (
      <div className="space-y-2">
        {summaryCallout}
        <div className="p-4 border border-gray-800 rounded text-xs text-gray-500 italic bg-gray-900/40">
          No changes — the new draft is identical to the previous version.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {summaryCallout}
      <div className="flex items-center justify-between flex-wrap gap-2">
        {label ? (
          <div className="text-xs text-gray-400 italic">{label}</div>
        ) : (
          <div />
        )}
        <div
          className="inline-flex text-xs rounded border border-gray-700 overflow-hidden"
          role="group"
          aria-label="Diff layout"
        >
          <button
            type="button"
            onClick={() => setViewType('split')}
            aria-pressed={viewType === 'split'}
            className={`px-3 py-1 ${
              viewType === 'split'
                ? 'bg-gray-700 text-gray-100'
                : 'bg-gray-900 text-gray-400 hover:bg-gray-800'
            }`}
          >
            Side-by-side
          </button>
          <button
            type="button"
            onClick={() => setViewType('unified')}
            aria-pressed={viewType === 'unified'}
            className={`px-3 py-1 border-l border-gray-700 ${
              viewType === 'unified'
                ? 'bg-gray-700 text-gray-100'
                : 'bg-gray-900 text-gray-400 hover:bg-gray-800'
            }`}
          >
            Unified
          </button>
        </div>
      </div>
      <div className="diff-view-dark overflow-x-auto border border-gray-800 rounded text-xs">
        <Diff viewType={viewType} diffType="modify" hunks={hunks}>
          {(renderHunks) =>
            renderHunks.map((hunk) => <Hunk key={hunk.content} hunk={hunk} />)
          }
        </Diff>
      </div>
    </div>
  );
}
