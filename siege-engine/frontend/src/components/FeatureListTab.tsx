import { XmlDocument } from './xml';
import { featureRenderers } from './xml';

/**
 * Slice the ``<features>...</features>`` subtree out of an
 * expansion draft / approved content blob and render it with
 * ``featureRenderers``. Used by the Features subtab on the
 * feature-expansion panel so the user can see the parsed
 * feature list without scrolling past the ``<introduction>``
 * preamble or the ``<vocabulary>`` sibling block.
 *
 * Accepts either the pending draft's raw XML or the approved
 * node's content. Returns a short "no content yet" message
 * when the input is empty or the features block is missing.
 */
const FEATURES_BLOCK_RE = /<features[\s\S]*?<\/features>/i;

export function FeatureListTab({ content }: { content: string | null | undefined }) {
  const trimmed = (content ?? '').trim();
  if (!trimmed) {
    return (
      <p className="text-xs text-gray-500 italic">
        No content yet — feature list will appear here once a draft lands.
      </p>
    );
  }

  const match = FEATURES_BLOCK_RE.exec(trimmed);
  if (!match) {
    return (
      <p className="text-xs text-gray-500 italic">
        Draft output is missing a <code>&lt;features&gt;</code> block, so
        there&apos;s nothing to list here yet. Check the Document tab for
        the raw content.
      </p>
    );
  }

  return <XmlDocument content={match[0]} renderers={featureRenderers} />;
}
