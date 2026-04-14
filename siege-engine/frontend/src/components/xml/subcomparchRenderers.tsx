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
 *       <dep to="sibling_sub_alias"/>
 *       <dep to="comp_parent_sibling"/>
 *     </dependencies>
 *   </subcomparch>
 *
 * Four sections, all fragments. Mirrors comparchRenderers shape
 * for the three fragment sections, and renders <dependencies>
 * with a distinct visual treatment for alias vs real-id targets
 * (alias = local sibling sub, ``comp_`` prefix = parent's
 * sibling top-level comp).
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
    const aliasDeps: string[] = [];
    const compIdDeps: string[] = [];
    for (const d of deps) {
      const to = d.attributes.to;
      const target = typeof to === 'string' ? to : '';
      if (!target) continue;
      if (target.startsWith('comp_')) {
        compIdDeps.push(target);
      } else {
        aliasDeps.push(target);
      }
    }
    return (
      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
          Dependencies
          <span className="ml-2 text-gray-600 font-normal normal-case tracking-normal">
            ({deps.length})
          </span>
        </h2>
        {aliasDeps.length > 0 && (
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">
              Same-parent siblings
            </div>
            <ul className="text-xs font-mono text-gray-400 space-y-0.5 m-0 pl-0 list-none">
              {aliasDeps.map((alias) => (
                <li key={`alias-${alias}`}>
                  <span className="text-gray-500">→ </span>
                  <span className="text-emerald-300">{alias}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {compIdDeps.length > 0 && (
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">
              Parent-sibling components
            </div>
            <ul className="text-xs font-mono text-gray-400 space-y-0.5 m-0 pl-0 list-none">
              {compIdDeps.map((compId) => (
                <li key={`id-${compId}`}>
                  <span className="text-gray-500">→ </span>
                  <span className="text-blue-300">{compId}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    );
  },

  // Consumed by parent renderers — null at the top level.
  dep: () => null,
};
