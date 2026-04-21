import type { XmlRendererMap } from './xml';
import { sliceXmlBlock } from '../lib/sliceXmlBlock';
import { XmlDocument } from './xml';

/**
 * Slice the ``<components>...</components>`` subtree out of a
 * sysarch draft / approved content blob and render it with the
 * caller-supplied renderer map (so the panel can thread in its
 * resp-name + pending-draft-kind context maps built via
 * ``makeSysarchRenderers``).
 *
 * Same spirit as ``FeatureListTab`` / ``RequirementsListTab``:
 * the Document tab now leads with the ``<introduction>`` preamble
 * (Phase-11 followup B4) followed by ``<techspec>``,
 * ``<components>``, ``<policies>``, etc., so a dedicated
 * Components tab lets users jump straight to the component list
 * without scrolling.
 */
export function SysarchComponentsTab({
  content,
  renderers,
}: {
  content: string | null | undefined;
  renderers: XmlRendererMap;
}) {
  if (!content || !content.trim()) {
    return (
      <p className="text-xs text-gray-500 italic">
        No content yet — the component list will appear here once a draft
        lands.
      </p>
    );
  }
  const slice = sliceXmlBlock(content, 'components');
  if (!slice) {
    return (
      <p className="text-xs text-gray-500 italic">
        Draft output is missing a <code>&lt;components&gt;</code> block,
        so there&apos;s nothing to list here yet. Check the Document tab
        for the raw content.
      </p>
    );
  }
  return <XmlDocument content={slice} renderers={renderers} />;
}
