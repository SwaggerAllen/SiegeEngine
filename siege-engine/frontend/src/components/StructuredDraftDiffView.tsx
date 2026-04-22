import { useMemo, useState } from 'react';
import { DraftDiffView } from './DraftDiffView';
import {
  extractDraftSections,
  type DraftDocKind,
  type DraftSection,
} from '../lib/extractDraftSections';

/**
 * Section-aware diff for the three structured bootstrap docs
 * (expansion, requirements, sysarch).
 *
 * Instead of feeding the whole XML to ``react-diff-view`` at once,
 * this component:
 *
 * 1. Parses each side into a list of per-entity sections (one
 *    feature / responsibility / component) via
 *    :func:`extractDraftSections`.
 * 2. Pairs matching sections across the before/after, classifying
 *    each as ``unchanged`` / ``changed`` / ``added`` / ``removed``.
 * 3. Renders a summary header plus one accordion per section,
 *    expanding changed/added/removed by default and collapsing
 *    unchanged so the user can jump straight to drift.
 *
 * Each accordion embeds a :component:`DraftDiffView` scoped to
 * just that section's XML — the Side-by-side / Unified toggle
 * lives on each entry, so you can pick a layout per section.
 *
 * Falls back to a full-document :component:`DraftDiffView` when
 * parsing fails or when a section list can't be built for the
 * requested ``kind``. Also falls back when the "before" side is
 * ``null`` — a brand-new bootstrap has no prior version to pair
 * against.
 */
export function StructuredDraftDiffView({
  before,
  after,
  kind,
  label,
}: {
  before: string | null;
  after: string;
  kind: DraftDocKind;
  label?: string;
}) {
  const pairs = useMemo(
    () => pairSections(before, after, kind),
    [before, after, kind],
  );

  // Fall back to the flat diff when we can't build structured
  // sections (parse error, no recognizable container, brand-new
  // bootstrap with ``before=null``, etc.). Callers get the same
  // render path they had pre-structured-diff.
  if (pairs === null) {
    return <DraftDiffView before={before} after={after} label={label} />;
  }

  const changeCount = pairs.filter((p) => p.status !== 'unchanged').length;

  return (
    <div className="space-y-3">
      {label && <div className="text-xs text-gray-400 italic">{label}</div>}
      <StructuredSummary pairs={pairs} />
      {changeCount === 0 ? (
        <p className="text-xs text-gray-500 italic">
          No per-section changes — the structured content is
          identical across the pin.
        </p>
      ) : (
        <ul className="space-y-2">
          {pairs.map((pair) => (
            <li key={pair.key}>
              <SectionAccordion pair={pair} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface SectionPair {
  key: string;
  label: string;
  kind: string;
  before: string | null;
  after: string | null;
  status: 'unchanged' | 'changed' | 'added' | 'removed';
}

function pairSections(
  before: string | null,
  after: string,
  kind: DraftDocKind,
): SectionPair[] | null {
  const beforeSections = extractDraftSections(before, kind);
  const afterSections = extractDraftSections(after, kind);
  // Need at least one parseable side to render anything structured.
  if (beforeSections === null && afterSections === null) return null;

  const beforeMap = new Map<string, DraftSection>();
  for (const s of beforeSections ?? []) beforeMap.set(s.key, s);
  const afterMap = new Map<string, DraftSection>();
  for (const s of afterSections ?? []) afterMap.set(s.key, s);

  // Ordered walk: after's order (current state) first, then any
  // removed entries from before at the end. Keeps the UI stable
  // when entries move in document order on a regen.
  const seen = new Set<string>();
  const pairs: SectionPair[] = [];

  for (const s of afterSections ?? []) {
    seen.add(s.key);
    const prior = beforeMap.get(s.key);
    pairs.push({
      key: s.key,
      label: s.label,
      kind: s.kind,
      before: prior?.xml ?? null,
      after: s.xml,
      status: !prior
        ? 'added'
        : prior.xml.trim() === s.xml.trim()
          ? 'unchanged'
          : 'changed',
    });
  }
  for (const s of beforeSections ?? []) {
    if (seen.has(s.key)) continue;
    pairs.push({
      key: s.key,
      label: s.label,
      kind: s.kind,
      before: s.xml,
      after: null,
      status: 'removed',
    });
  }

  return pairs;
}

function StructuredSummary({ pairs }: { pairs: SectionPair[] }) {
  const counts = pairs.reduce(
    (acc, p) => {
      acc[p.status] += 1;
      return acc;
    },
    { unchanged: 0, changed: 0, added: 0, removed: 0 },
  );
  return (
    <div className="flex items-center gap-3 flex-wrap text-xs">
      <SummaryBadge label="changed" count={counts.changed} tone="amber" />
      <SummaryBadge label="added" count={counts.added} tone="green" />
      <SummaryBadge label="removed" count={counts.removed} tone="red" />
      <SummaryBadge
        label="unchanged"
        count={counts.unchanged}
        tone="gray"
      />
    </div>
  );
}

function SummaryBadge({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: 'amber' | 'green' | 'red' | 'gray';
}) {
  const toneClass = {
    amber: 'bg-amber-900/40 text-amber-300',
    green: 'bg-green-900/40 text-green-300',
    red: 'bg-red-900/40 text-red-300',
    gray: 'bg-gray-800 text-gray-400',
  }[tone];
  return (
    <span className={`px-2 py-0.5 rounded ${toneClass}`}>
      {count} {label}
    </span>
  );
}

function SectionAccordion({ pair }: { pair: SectionPair }) {
  const initiallyOpen = pair.status !== 'unchanged';
  const [open, setOpen] = useState<boolean>(initiallyOpen);
  const badge = statusBadge(pair.status);
  return (
    <div className="border border-gray-800 rounded">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-gray-900"
      >
        <span className="text-[10px] uppercase tracking-wide text-gray-500 w-24 shrink-0">
          {pair.kind}
        </span>
        <span className="text-sm flex-1 min-w-0 truncate">{pair.label}</span>
        {badge}
      </button>
      {open && (
        <div className="px-3 pb-3 pt-1 border-t border-gray-800">
          {pair.status === 'added' ? (
            <AddedSectionBody after={pair.after ?? ''} />
          ) : pair.status === 'removed' ? (
            <RemovedSectionBody before={pair.before ?? ''} />
          ) : (
            <DraftDiffView
              before={pair.before}
              after={pair.after ?? ''}
            />
          )}
        </div>
      )}
    </div>
  );
}

function statusBadge(status: SectionPair['status']) {
  const { tone, label } =
    status === 'added'
      ? { tone: 'bg-green-900/60 text-green-300', label: 'added' }
      : status === 'removed'
        ? { tone: 'bg-red-900/60 text-red-300', label: 'removed' }
        : status === 'changed'
          ? { tone: 'bg-amber-900/60 text-amber-300', label: 'changed' }
          : { tone: 'bg-gray-800 text-gray-500', label: 'unchanged' };
  return (
    <span
      className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded ${tone} shrink-0`}
    >
      {label}
    </span>
  );
}

function AddedSectionBody({ after }: { after: string }) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-green-300/80 italic">
        New section — no prior version.
      </p>
      <pre className="text-xs bg-gray-950 border border-gray-800 rounded p-2 overflow-x-auto whitespace-pre-wrap">
        {after}
      </pre>
    </div>
  );
}

function RemovedSectionBody({ before }: { before: string }) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-red-300/80 italic">
        Removed — no longer present in the current draft.
      </p>
      <pre className="text-xs bg-gray-950 border border-gray-800 rounded p-2 overflow-x-auto whitespace-pre-wrap">
        {before}
      </pre>
    </div>
  );
}
