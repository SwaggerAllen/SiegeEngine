import { CollapsibleSection } from './CollapsibleSection';
import { Paragraphs } from './Paragraphs';
import type { XmlRendererMap } from './types';
import { findChildren, textContent } from './types';

/**
 * Renderer overrides for the subcomparch schema:
 *
 *   <subcomparch>
 *     <technical-specification>…</technical-specification>
 *     <public-surface>…</public-surface>
 *     <private-surface>…</private-surface>
 *     <dependencies>
 *       <dep to="comp_sibling12"/>
 *       <dep to="comp_parentsi"/>
 *     </dependencies>
 *   </subcomparch>
 *
 * Four sections, all fragments. Mirrors comparchRenderers shape
 * for the three fragment sections, and renders <dependencies>
 * as a flat list of ``comp_*`` targets — the tier no longer
 * uses local aliases because siblings already have stable IDs
 * at subcomparch generation time.
 */
export const subcomparchRenderers: XmlRendererMap = {
  subcomparch: (node, ctx) => (
    <div className="not-prose space-y-6">{ctx.renderChildren(node.children)}</div>
  ),

  'technical-specification': (node) => (
    <CollapsibleSection summary="Technical Specification">
      <Paragraphs text={textContent(node)} />
    </CollapsibleSection>
  ),

  'public-surface': (node) => (
    <CollapsibleSection summary="Public Surface">
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </CollapsibleSection>
  ),

  'private-surface': (node) => (
    <CollapsibleSection summary="Private Surface">
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </CollapsibleSection>
  ),

  dependencies: (node) => {
    const deps = findChildren(node, 'dep');
    const meta = (
      <span className="text-gray-500">{deps.length === 0 ? 'none' : deps.length}</span>
    );
    if (deps.length === 0) {
      return (
        <CollapsibleSection summary="Dependencies" meta={meta}>
          <p className="text-sm text-gray-500 italic m-0">
            Leaf subcomponent — no dependencies.
          </p>
        </CollapsibleSection>
      );
    }
    const targets: string[] = [];
    for (const d of deps) {
      const to = d.attributes.to;
      const target = typeof to === 'string' ? to : '';
      if (target) targets.push(target);
    }
    return (
      <CollapsibleSection summary="Dependencies" meta={meta}>
        <ul className="text-xs font-mono text-gray-400 space-y-0.5 m-0 pl-0 list-none">
          {targets.map((target) => (
            <li key={`dep-${target}`}>
              <span className="text-gray-500">→ </span>
              <span className="text-blue-300">{target}</span>
            </li>
          ))}
        </ul>
      </CollapsibleSection>
    );
  },

  // Consumed by parent renderers — null at the top level.
  dep: () => null,
};
