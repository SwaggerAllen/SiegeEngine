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
    <section className="space-y-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
        Technical Specification
      </h2>
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </section>
  ),

  'public-surface': (node) => (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
        Public Surface
      </h2>
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </section>
  ),

  'private-surface': (node) => (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
        Private Surface
      </h2>
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </section>
  ),

  dependencies: (node) => {
    const deps = findChildren(node, 'dep');
    if (deps.length === 0) {
      return (
        <section className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
            Dependencies
          </h2>
          <p className="text-sm text-gray-500 italic m-0">
            Leaf subcomponent — no dependencies.
          </p>
        </section>
      );
    }
    const targets: string[] = [];
    for (const d of deps) {
      const to = d.attributes.to;
      const target = typeof to === 'string' ? to : '';
      if (target) targets.push(target);
    }
    return (
      <section className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
          Dependencies
          <span className="ml-2 text-gray-600 font-normal normal-case tracking-normal">
            ({deps.length})
          </span>
        </h2>
        <ul className="text-xs font-mono text-gray-400 space-y-0.5 m-0 pl-0 list-none">
          {targets.map((target) => (
            <li key={`dep-${target}`}>
              <span className="text-gray-500">→ </span>
              <span className="text-blue-300">{target}</span>
            </li>
          ))}
        </ul>
      </section>
    );
  },

  // Consumed by parent renderers — null at the top level.
  dep: () => null,
};
