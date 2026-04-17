import { CollapsibleSection } from './CollapsibleSection';
import { Paragraphs } from './Paragraphs';
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
 *
 * The factory form lets the owning panel (``SysarchPanel``) close
 * over three live maps:
 *
 * - ``respNames``: ``resp_*`` id → name, used in each component
 *   card's "Responsibilities" list and each policy card's
 *   "requires" line to render ``name (resp_xxxxxxxx)`` instead
 *   of bare IDs.
 * - ``pendingByName``: component name → pending-draft kind
 *   (``"subreqs"`` / ``"comparch"`` / ``"subcomparch"``), used to
 *   badge component cards with a "waiting on approval" indicator.
 *   Keyed by name because the sysarch document only contains
 *   aliases + names; the owning panel resolves name → comp_id via
 *   the components list query and hands the name-keyed lookup in.
 *
 * Callers that don't need either map can use the default
 * module-level ``sysarchRenderers`` export (empty maps → bare
 * IDs, no waiting badges).
 */
export function makeSysarchRenderers(
  respNames: Record<string, string> = {},
  pendingByName: Record<string, string> = {}
): XmlRendererMap {
  const WAITING_LABELS: Record<string, string> = {
    subreqs: 'Waiting — subreqs',
    comparch: 'Waiting — comparch',
    subcomparch: 'Waiting — subcomparch',
  };
  const renderRespId = (rid: string) => {
    const name = respNames[rid];
    if (!name) return rid;
    return `${name} (${rid})`;
  };
  return {
  sysarch: (node, ctx) => (
    <div className="not-prose space-y-6">{ctx.renderChildren(node.children)}</div>
  ),

  techspec: (node) => (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
        System Technical Specification
      </h2>
      <Paragraphs text={textContent(node)} />
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
        <div className="space-y-2">
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
    const pendingKind = pendingByName[name];
    const cardBorderClass = pendingKind ? 'border-amber-500/60' : '';
    const summary = (
      <span className="flex items-baseline flex-wrap gap-x-2 gap-y-1">
        <span className="font-semibold text-white text-sm">{name}</span>
        <span className="text-xs font-mono text-gray-500">{alias}</span>
      </span>
    );
    const meta = (
      <>
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
        {pendingKind && (
          <span
            className="text-xs uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-200 border border-amber-500/40"
            title={`A ${pendingKind} draft for this component is waiting on your approval`}
          >
            {WAITING_LABELS[pendingKind] ?? 'Waiting'}
          </span>
        )}
      </>
    );
    return (
      <CollapsibleSection
        summary={summary}
        meta={meta}
        className={cardBorderClass}
      >
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
            <ul className="text-xs text-gray-400 space-y-0.5 m-0 pl-0 list-none">
              {respIds.map((rid) => {
                const name = respNames[rid];
                return (
                  <li key={rid} className="font-mono">
                    {name ? (
                      <>
                        <span className="text-gray-200">{name}</span>{' '}
                        <span className="text-gray-500">({rid})</span>
                      </>
                    ) : (
                      rid
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </CollapsibleSection>
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
            requires{' '}
            <span className="font-mono text-gray-300">{renderRespId(required)}</span>
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
}

/**
 * Back-compat module-level export: a renderer map with no
 * resp-name resolution. Existing callers (tests, non-panel
 * usages) get bare resp IDs; the dashboard's ``SysarchPanel``
 * opts into the factory form so component cards can show names.
 */
export const sysarchRenderers: XmlRendererMap = makeSysarchRenderers();
