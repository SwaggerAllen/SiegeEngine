// Public surface of the XML rendering package.
//
// Schema-agnostic:
//   - XmlDocument    — the renderer component
//   - parseXml       — parse raw XML into the canonical XmlNode tree
//   - types          — XmlNode, XmlElement, XmlText, helpers
//   - defaultRenderers — fallback renderer for unknown tags
//
// Schema-specific:
//   - featureRenderers — renderer map for <features>/<group>/<feature>
//
// Future phases add siblings here: reqsRenderers, sysarchRenderers,
// subreqsRenderers, manifestRenderers. Each is a plain object of
// the XmlRendererMap shape.

export { XmlDocument } from './XmlDocument';
export { parseXml } from './parser';
export { renderUnknownElement } from './defaultRenderers';
export { comparchRenderers } from './comparchRenderers';
export { featureRenderers } from './featureRenderers';
export { implRenderers } from './implRenderers';
export { referencesRenderers } from './referencesRenderers';
export {
  makeRequirementsRenderers,
  requirementsRenderers,
} from './requirementsRenderers';
export { subcomparchRenderers } from './subcomparchRenderers';
export { subreqsRenderers } from './subreqsRenderers';
export { makeSysarchRenderers, sysarchRenderers } from './sysarchRenderers';
export type {
  XmlElement,
  XmlNode,
  XmlRendererMap,
  XmlRenderContext,
  XmlTagRenderer,
  XmlText,
} from './types';
export {
  findChild,
  findChildText,
  findChildren,
  hasChild,
  textContent,
} from './types';
