import { CollapsibleSection } from './CollapsibleSection';
import { Paragraphs } from './Paragraphs';
import type { XmlRendererMap } from './types';
import { findChild, findChildText, findChildren, textContent } from './types';

/**
 * Renderer overrides for the comparch schema:
 *
 *   <comparch>
 *     <technical-specification>…</technical-specification>
 *     <public-surface>…</public-surface>
 *     <private-surface>…</private-surface>
 *     <policies><policy>…</policy>…</policies>
 *     <dependencies><dep to="comp_..."/></dependencies>
 *     <subcomponents>
 *       <subcomponent alias="...">
 *         <name>…</name>
 *         <role>…</role>
 *         <api-intent>…</api-intent>
 *         <responsibilities><resp id="resp_..."/></responsibilities>
 *         [<foundation/>]
 *       </subcomponent>
 *       …
 *     </subcomponents>
 *     <sub-dependencies><dep from="alias1" to="alias2"/></sub-dependencies>
 *   </comparch>
 *
 * Seven sections: the three fragment sections render as prose
 * blocks, policies as cards, dependencies as a compact list,
 * subcomponents as a grid of cards (mirroring sysarch's
 * component cards minus the kind badge since it's inherited),
 * and sub-dependencies as an arrow list.
 */
export const comparchRenderers: XmlRendererMap = {
  comparch: (node, ctx) => (
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

  policies: (node, ctx) => {
    const policies = findChildren(node, 'policy');
    if (policies.length === 0) return null;
    return (
      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
          Component-local Policies
          <span className="ml-2 text-gray-600 font-normal normal-case tracking-normal">
            ({policies.length})
          </span>
        </h2>
        <div className="space-y-2">{policies.map((p, i) => ctx.renderNode(p, i))}</div>
      </section>
    );
  },

  policy: (node) => {
    const name = findChildText(node, 'name') ?? 'Untitled';
    const trigger = findChildText(node, 'trigger') ?? '';
    const required = findChildText(node, 'required') ?? '';
    const rationale = findChildText(node, 'rationale') ?? '';
    const summary = (
      <span className="flex items-baseline flex-wrap gap-x-2 gap-y-1">
        <span className="font-semibold text-white text-sm">{name}</span>
        {trigger && (
          <span className="text-xs italic text-gray-400 font-normal">on {trigger}</span>
        )}
      </span>
    );
    return (
      <CollapsibleSection summary={summary}>
        {required && (
          <div className="text-xs text-gray-400">
            requires <span className="font-mono text-gray-300">{required}</span>
          </div>
        )}
        {rationale && (
          <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">{rationale}</p>
        )}
      </CollapsibleSection>
    );
  },

  dependencies: (node) => {
    const deps = findChildren(node, 'dep');
    if (deps.length === 0) return null;
    return (
      <section className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
          External Dependencies
          <span className="ml-2 text-gray-600 font-normal normal-case tracking-normal">
            ({deps.length})
          </span>
        </h2>
        <ul className="text-xs font-mono text-gray-400 space-y-0.5 m-0 pl-0 list-none">
          {deps.map((d, i) => {
            const to = d.attributes.to;
            const target = typeof to === 'string' ? to : '';
            return (
              <li key={i}>
                <span className="text-gray-500">→ </span>
                <span className="text-gray-300">{target}</span>
              </li>
            );
          })}
        </ul>
      </section>
    );
  },

  subcomponents: (node, ctx) => {
    const subs = findChildren(node, 'subcomponent');
    if (subs.length === 0) {
      return (
        <section className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
            Subcomponents
          </h2>
          <p className="text-sm text-gray-500 italic m-0">
            Un-fanned-out: this component does not decompose into subcomponents.
          </p>
        </section>
      );
    }
    return (
      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
          Subcomponents
          <span className="ml-2 text-gray-600 font-normal normal-case tracking-normal">
            ({subs.length})
          </span>
        </h2>
        <div className="space-y-2">
          {subs.map((s, i) => ctx.renderNode(s, i))}
        </div>
      </section>
    );
  },

  subcomponent: (node) => {
    const aliasAttr = node.attributes.alias;
    const alias = typeof aliasAttr === 'string' ? aliasAttr : '?';
    const name = findChildText(node, 'name') ?? 'Untitled';
    const role = findChildText(node, 'role') ?? '';
    const apiIntent = findChildText(node, 'api-intent') ?? '';
    const isFoundation =
      node.children.some((c) => c.type === 'element' && c.name === 'foundation');
    const respsNode = findChild(node, 'responsibilities');
    const respIds: string[] = respsNode
      ? respsNode.children
          .filter((c) => c.type === 'element' && c.name === 'resp')
          .map((c) => {
            if (c.type !== 'element') return '';
            const id = c.attributes.id;
            return typeof id === 'string' ? id : '';
          })
          .filter(Boolean)
      : [];
    const summary = (
      <span className="flex items-baseline flex-wrap gap-x-2 gap-y-1">
        <span className="font-semibold text-white text-sm">{name}</span>
        <span className="text-xs font-mono text-gray-500">{alias}</span>
      </span>
    );
    const meta = isFoundation ? (
      <span
        className="text-xs uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-200"
        title="Foundation subcomponent — owns the component's root folder territory"
      >
        foundation
      </span>
    ) : undefined;
    return (
      <CollapsibleSection summary={summary} meta={meta}>
        {role && (
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">
              Role
            </div>
            <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">{role}</p>
          </div>
        )}
        {apiIntent && (
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">
              API intent
            </div>
            <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
              {apiIntent}
            </p>
          </div>
        )}
        {respIds.length > 0 && (
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">
              Subresponsibilities
            </div>
            <div className="flex flex-wrap gap-1">
              {respIds.map((rid) => (
                <span
                  key={rid}
                  className="text-[10px] font-mono bg-gray-900/60 border border-gray-700 rounded px-1.5 py-0.5 text-gray-400"
                >
                  {rid}
                </span>
              ))}
            </div>
          </div>
        )}
      </CollapsibleSection>
    );
  },

  'sub-dependencies': (node) => {
    const deps = findChildren(node, 'dep');
    if (deps.length === 0) return null;
    return (
      <section className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
          Sub-Dependencies
          <span className="ml-2 text-gray-600 font-normal normal-case tracking-normal">
            ({deps.length})
          </span>
        </h2>
        <ul className="text-xs font-mono text-gray-400 space-y-0.5 m-0 pl-0 list-none">
          {deps.map((d, i) => {
            const from = typeof d.attributes.from === 'string' ? d.attributes.from : '';
            const to = typeof d.attributes.to === 'string' ? d.attributes.to : '';
            return (
              <li key={i}>
                <span className="text-gray-300">{from}</span>
                <span className="mx-1">→</span>
                <span className="text-gray-300">{to}</span>
              </li>
            );
          })}
        </ul>
      </section>
    );
  },

  // Consumed by parent renderers — null at the top level.
  name: () => null,
  role: () => null,
  'api-intent': () => null,
  responsibilities: () => null,
  resp: () => null,
  foundation: () => null,
  trigger: () => null,
  required: () => null,
  rationale: () => null,
  dep: () => null,
};
