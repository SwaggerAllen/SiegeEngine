import type { XmlRendererMap } from './types';
import { findChild, findChildText, findChildren, hasChild, textContent } from './types';

/**
 * Renderer overrides for the sysarch schema:
 *
 *   <sysarch>
 *     <techspec>…project-level tech spec…</techspec>
 *     <components>
 *       <component alias="billing">
 *         <name>Billing</name>
 *         <kind>domain</kind>
 *         <role>…</role>
 *         <api-intent>…</api-intent>
 *         <responsibilities>
 *           <resp id="resp_..."/>
 *         </responsibilities>
 *         [<foundation/>]
 *       </component>
 *       …
 *     </components>
 *     <policies>
 *       <policy>
 *         <name>…</name><trigger>…</trigger>
 *         <required>resp_…</required><rationale>…</rationale>
 *       </policy>
 *       …
 *     </policies>
 *     <dependencies><dep from="…" to="…"/>…</dependencies>
 *     <domain-parent><parent from="…" to="…"/>…</domain-parent>
 *   </sysarch>
 *
 * The renderer walks this tree and produces a labeled document
 * view: a techspec paragraph, a grid of component cards, a list
 * of policy cards, and compact arrow lists for edges.
 */
export const sysarchRenderers: XmlRendererMap = {
  sysarch: (node, ctx) => (
    <div className="not-prose space-y-6">{ctx.renderChildren(node.children)}</div>
  ),

  techspec: (node) => (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
        System Technical Specification
      </h2>
      <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
        {textContent(node).trim()}
      </p>
    </section>
  ),

  components: (node, ctx) => {
    const components = findChildren(node, 'component');
    return (
      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
          Components
          <span className="ml-2 text-gray-600 font-normal normal-case tracking-normal">
            ({components.length})
          </span>
        </h2>
        <div className="grid gap-3 md:grid-cols-2">
          {components.map((c, i) => ctx.renderNode(c, i))}
        </div>
      </section>
    );
  },

  component: (node) => {
    const alias = node.attributes.alias ?? '?';
    const name = findChildText(node, 'name') ?? 'Untitled';
    const kind = findChildText(node, 'kind') ?? 'domain';
    const role = findChildText(node, 'role') ?? '';
    const apiIntent = findChildText(node, 'api-intent') ?? '';
    const isFoundation = hasChild(node, 'foundation');
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
    return (
      <article className="bg-gray-800/40 border border-gray-700 rounded p-4 space-y-2">
        <header className="space-y-1">
          <div className="flex items-baseline flex-wrap gap-x-2 gap-y-1">
            <h3 className="font-semibold text-white m-0 text-sm">{name}</h3>
            <span className="text-xs font-mono text-gray-500">{alias}</span>
            <span
              className={
                'text-xs uppercase tracking-wider px-1.5 py-0.5 rounded ' +
                (kind === 'presentational'
                  ? 'bg-purple-900/40 text-purple-200'
                  : 'bg-blue-900/40 text-blue-200')
              }
            >
              {kind}
            </span>
            {isFoundation && (
              <span
                className="text-xs uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-200"
                title="Foundation component — owns the root folder territory"
              >
                foundation
              </span>
            )}
          </div>
        </header>
        {role && (
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">Role</div>
            <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">{role}</p>
          </div>
        )}
        {apiIntent && (
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">
              API intent
            </div>
            <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">{apiIntent}</p>
          </div>
        )}
        {respIds.length > 0 && (
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">
              Responsibilities
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
      </article>
    );
  },

  policies: (node, ctx) => {
    const policies = findChildren(node, 'policy');
    if (policies.length === 0) return null;
    return (
      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
          Top-level Policies
          <span className="ml-2 text-gray-600 font-normal normal-case tracking-normal">
            ({policies.length})
          </span>
        </h2>
        <div className="space-y-2">
          {policies.map((p, i) => ctx.renderNode(p, i))}
        </div>
      </section>
    );
  },

  policy: (node) => {
    const name = findChildText(node, 'name') ?? 'Untitled';
    const trigger = findChildText(node, 'trigger') ?? '';
    const required = findChildText(node, 'required') ?? '';
    const rationale = findChildText(node, 'rationale') ?? '';
    return (
      <article className="bg-gray-800/40 border border-gray-700 rounded p-3 space-y-1">
        <div className="flex items-baseline flex-wrap gap-x-2 gap-y-1">
          <h3 className="font-semibold text-white m-0 text-sm">{name}</h3>
          {trigger && (
            <span className="text-xs italic text-gray-400">on {trigger}</span>
          )}
        </div>
        {required && (
          <div className="text-xs text-gray-400">
            requires{' '}
            <span className="font-mono text-gray-300">{required}</span>
          </div>
        )}
        {rationale && (
          <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">{rationale}</p>
        )}
      </article>
    );
  },

  dependencies: (node) => {
    const deps = findChildren(node, 'dep');
    if (deps.length === 0) return null;
    return (
      <section className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
          Dependencies
          <span className="ml-2 text-gray-600 font-normal normal-case tracking-normal">
            ({deps.length})
          </span>
        </h2>
        <ul className="text-xs font-mono text-gray-400 space-y-0.5 m-0 pl-0 list-none">
          {deps.map((d, i) => (
            <li key={i}>
              <span className="text-gray-300">{d.attributes.from}</span>
              <span className="mx-1">→</span>
              <span className="text-gray-300">{d.attributes.to}</span>
            </li>
          ))}
        </ul>
      </section>
    );
  },

  'domain-parent': (node) => {
    const parents = findChildren(node, 'parent');
    if (parents.length === 0) return null;
    return (
      <section className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
          Domain-parent edges
          <span className="ml-2 text-gray-600 font-normal normal-case tracking-normal">
            ({parents.length})
          </span>
        </h2>
        <ul className="text-xs font-mono text-gray-400 space-y-0.5 m-0 pl-0 list-none">
          {parents.map((p, i) => (
            <li key={i}>
              <span className="text-purple-300">{p.attributes.from}</span>
              <span className="mx-1">▶</span>
              <span className="text-blue-300">{p.attributes.to}</span>
            </li>
          ))}
        </ul>
      </section>
    );
  },

  // Tags consumed by parent renderers — return null at the top level.
  name: () => null,
  kind: () => null,
  role: () => null,
  'api-intent': () => null,
  responsibilities: () => null,
  resp: () => null,
  foundation: () => null,
  trigger: () => null,
  required: () => null,
  rationale: () => null,
  dep: () => null,
  parent: () => null,
};
