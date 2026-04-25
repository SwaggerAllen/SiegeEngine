import { useMemo } from 'react';
import { sliceXmlBlock } from '../lib/sliceXmlBlock';
import { parseXml } from './xml';
import { SubresponsibilityCard } from './xml/SubresponsibilityCard';
import type { XmlElement } from './xml/types';

/**
 * Subresponsibilities subtab — parses a subreqs draft / approved
 * content blob and renders subresps grouped under their parent
 * top-level resps. Mirrors the layout pattern of
 * ``RequirementsListTab`` (where features are grouped under
 * responsibilities) but at one tier deeper: parent resps own
 * subresps via ``<derived-from>`` references, and each subresp
 * carries its own ``<feats>`` tag list rendered as collapsible
 * count pills via :component:`SubresponsibilityCard`.
 *
 * The parent resp set comes from the project structure rather
 * than the subreqs XML itself — the structure carries the resp
 * names which the rendered headers display, and surfaces parent
 * resps with no covering subresps as an empty bucket so the user
 * can spot a coverage gap (which the validator should have
 * caught at generation time, but the visual confirmation is
 * still useful).
 */
export function SubreqsListTab({
  content,
  parentResps,
  featureNames = {},
}: {
  content: string | null | undefined;
  parentResps: ReadonlyArray<{ id: string; name: string }>;
  featureNames?: Record<string, string>;
}) {
  const grouped = useMemo(() => parseSubresps(content), [content]);

  if (!content || !content.trim()) {
    return (
      <p className="text-xs text-gray-500 italic">
        No content yet — subresponsibilities will appear here once a
        draft lands.
      </p>
    );
  }
  if (!grouped) {
    return (
      <p className="text-xs text-gray-500 italic">
        Draft output is missing a <code>&lt;subrequirements&gt;</code>{' '}
        block, so there&apos;s nothing to list here yet. Check the
        Document tab for the raw content.
      </p>
    );
  }
  if (parentResps.length === 0) {
    return (
      <p className="text-xs text-gray-500 italic">
        This component has no top-level responsibilities assigned
        yet — subresponsibilities decompose those, so the list will
        populate once sysarch routes resps to this component.
      </p>
    );
  }

  return (
    <div className="not-prose space-y-4">
      {parentResps.map((parent) => {
        const subs = grouped.get(parent.id) ?? [];
        return (
          <section
            key={parent.id}
            className="border border-gray-800 rounded bg-gray-950/40"
          >
            <header className="px-3 py-2 border-b border-gray-800 bg-gray-900/40">
              <div className="text-sm font-semibold text-gray-100">
                {parent.name}
              </div>
              <div className="text-[10px] font-mono text-gray-500 mt-0.5">
                {parent.id}
              </div>
            </header>
            {subs.length === 0 ? (
              <p className="px-3 py-2 text-xs italic text-amber-400">
                No subresponsibilities derived from this parent. The
                validator should have rejected this — surface this
                draft for review.
              </p>
            ) : (
              <ul className="divide-y divide-gray-800">
                {subs.map((sub, idx) => (
                  <li key={`${parent.id}-${idx}`} className="px-3 py-2">
                    <SubresponsibilityCard
                      name={sub.name}
                      feats={sub.feats}
                      parentIds={sub.derivedFrom}
                      featureNames={featureNames}
                    />
                    {sub.derivedFrom.length > 1 && (
                      <div className="mt-1 text-[10px] uppercase tracking-wider text-gray-500">
                        shared · {sub.derivedFrom.length} parents
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
      {/* Surface orphan subresps — derived-from references that
       * don't match any parent resp in the structure. Should be
       * impossible (the validator's cross-component leak check
       * rejects unknown IDs), but if it ever happens we don't
       * silently drop them. */}
      {(() => {
        const knownIds = new Set(parentResps.map((p) => p.id));
        const orphaned: SubrespEntry[] = [];
        for (const subs of grouped.values()) {
          for (const sub of subs) {
            if (!sub.derivedFrom.some((id) => knownIds.has(id))) {
              orphaned.push(sub);
            }
          }
        }
        if (orphaned.length === 0) return null;
        return (
          <section className="border border-amber-800 rounded bg-amber-950/30 p-3">
            <h4 className="text-xs font-semibold text-amber-300 uppercase tracking-wide mb-2">
              Orphaned subresps ({orphaned.length})
            </h4>
            <p className="text-xs text-amber-200 mb-2">
              These subresps reference parent resp IDs not in this
              component&apos;s assigned set. Cross-component leak;
              regenerate.
            </p>
            <ul className="space-y-1.5 text-xs text-gray-300">
              {orphaned.map((sub, idx) => (
                <li key={idx}>
                  <span className="font-medium">{sub.name}</span> —
                  derived from{' '}
                  <span className="font-mono text-gray-500">
                    {sub.derivedFrom.join(', ')}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        );
      })()}
    </div>
  );
}

interface SubrespEntry {
  name: string;
  feats: string[];
  derivedFrom: string[];
}

/**
 * Parse the ``<subrequirements>`` block out of the draft content
 * and return a map of ``parent_resp_id → SubrespEntry[]``. A
 * single subresp can appear under multiple parents (each
 * ``derived-from`` ref produces an entry). Returns ``null`` when
 * the content has no ``<subrequirements>`` block at all so the
 * tab can render its own missing-block hint.
 */
function parseSubresps(
  content: string | null | undefined,
): Map<string, SubrespEntry[]> | null {
  if (!content) return null;
  const slice = sliceXmlBlock(content, 'subrequirements');
  if (!slice) return null;
  const tree = parseXml(slice);
  if (!tree || tree.name !== 'subrequirements') return new Map();

  const grouped = new Map<string, SubrespEntry[]>();
  for (const child of tree.children) {
    if (child.type !== 'element' || child.name !== 'subresponsibility') {
      continue;
    }
    const name = textOf(child, 'name') ?? 'Untitled';
    const feats: string[] = [];
    const derivedFrom: string[] = [];
    for (const sub of child.children) {
      if (sub.type !== 'element') continue;
      if (sub.name === 'feats') {
        for (const featChild of sub.children) {
          if (featChild.type !== 'element' || featChild.name !== 'feat') continue;
          const id = featChild.attributes.id;
          if (typeof id === 'string') feats.push(id);
        }
      } else if (sub.name === 'derived-from') {
        for (const respChild of sub.children) {
          if (respChild.type !== 'element' || respChild.name !== 'resp') continue;
          const id = respChild.attributes.id;
          if (typeof id === 'string') derivedFrom.push(id);
        }
      }
    }
    const entry: SubrespEntry = { name, feats, derivedFrom };
    for (const parentId of derivedFrom) {
      const bucket = grouped.get(parentId);
      if (bucket) bucket.push(entry);
      else grouped.set(parentId, [entry]);
    }
  }
  return grouped;
}

function textOf(element: XmlElement, childName: string): string | null {
  for (const c of element.children) {
    if (c.type === 'element' && c.name === childName) {
      const parts: string[] = [];
      for (const part of c.children) {
        if (part.type === 'text') parts.push(part.value);
      }
      const joined = parts.join('').trim();
      return joined || null;
    }
  }
  return null;
}
