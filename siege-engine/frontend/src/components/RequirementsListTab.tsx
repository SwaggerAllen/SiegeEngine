import { useMemo } from 'react';
import { sliceXmlBlock } from '../lib/sliceXmlBlock';
import { XmlDocument } from './xml';
import { makeRequirementsRenderers } from './xml';

/**
 * Slice the ``<requirements>...</requirements>`` subtree out of a
 * reqs draft / approved content blob and render it with
 * ``makeRequirementsRenderers``. Parallels ``FeatureListTab`` —
 * the requirements panel's Document tab shows the
 * ``<introduction>`` block on top (Phase-11 followup B4) and
 * scrolling past it every regen is noisy.
 *
 * Renderers need the project's feature-name map so
 * ``<feats><feat id="feat_xxxx"/></feats>`` renders as
 * ``Billing (feat_xxxx)`` instead of bare IDs. The parent
 * `RequirementsPanel` passes it in since it owns the features
 * query.
 */
export function RequirementsListTab({
  content,
  featureNames,
}: {
  content: string | null | undefined;
  featureNames: Record<string, string>;
}) {
  const renderers = useMemo(
    () => makeRequirementsRenderers(featureNames),
    [featureNames],
  );
  if (!content || !content.trim()) {
    return (
      <p className="text-xs text-gray-500 italic">
        No content yet — the responsibility list will appear here once a
        draft lands.
      </p>
    );
  }
  const slice = sliceXmlBlock(content, 'requirements');
  if (!slice) {
    return (
      <p className="text-xs text-gray-500 italic">
        Draft output is missing a <code>&lt;requirements&gt;</code> block,
        so there&apos;s nothing to list here yet. Check the Document tab
        for the raw content.
      </p>
    );
  }
  return <XmlDocument content={slice} renderers={renderers} />;
}
