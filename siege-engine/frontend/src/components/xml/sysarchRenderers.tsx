import { CollapsibleSection } from './CollapsibleSection';
import type { XmlRendererMap } from './types';
import { findChild, findChildText, findChildren, hasChild, textContent } from './types';

/**
 * Renderer overrides for the sysarch schema:
 *
 *   <sysarch>
 *     <techspec>
 *       <runtime>…</runtime><persistence>…</persistence>
 *       <write-path>…</write-path><concurrency>…</concurrency>
 *       <testing>…</testing><deploy>…</deploy>
 *       <technologies>…</technologies>
 *     </techspec>
 *     <components>
 *       <component alias="billing">
 *         <name>Billing</name>
 *         <kind>domain</kind>
 *         <purpose>…</purpose>
 *         <owned-invariants><invariant>…</invariant>…</owned-invariants>
 *         <primary-operations><operation>…</operation>…</primary-operations>
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

  techspec: (node) => {
    const BLOCK_LABELS: Array<[string, string]> = [
      ['runtime', 'Runtime'],
      ['persistence', 'Persistence'],
      ['write-path', 'Write path'],
      ['concurrency', 'Concurrency'],
      ['testing', 'Testing'],
      ['deploy', 'Deploy'],
      ['technologies', 'Technologies'],
    ];
    return (
      <section className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 m-0">
          System Technical Specification
        </h2>
        <dl className="space-y-2 m-0">
          {BLOCK_LABELS.map(([tag, label]) => {
            const text = findChildText(node, tag);
            if (!text) return null;
            return (
              <div key={tag} className="space-y-0.5">
                <dt className="text-[10px] uppercase tracking-wider text-gray-500">
                  {label}
                </dt>
                <dd className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
                  {text}
                </dd>
              </div>
            );
          })}
        </dl>
      </section>
    );
  },

  components: (node, ctx) => {
    const components = findChildren(node, 'component');
    // Orphan-resp enumeration: linear pass over every
    // ``<component kind="domain">/<responsibilities>/<resp>`` child
    // to collect which top-level resp IDs the draft assigns. Diff
    // against ``respNames`` (passed in by ``SysarchPanel`` with the
    // project's full top-level resp roster) and render a warning
    // for any known resp the draft fails to place. Only runs when
    // a non-empty ``respNames`` map is available — the default
    // module-level export passes ``{}`` so bare-ID callers skip
    // the check cleanly.
    //
    // Note: the backend validator rejects orphans at approval time,
    // so this panel only ever surfaces them on *pending* drafts —
    // which is exactly when the user wants to see them, since a
    // partial regen may have dropped a resp that the user needs to
    // ask the LLM to restore.
    const assigned = new Set<string>();
    for (const comp of components) {
      const kind = findChildText(comp, 'kind') ?? 'domain';
      if (kind !== 'domain') continue;
      const respsNode = findChild(comp, 'responsibilities');
      if (!respsNode) continue;
      for (const child of respsNode.children) {
        if (child.type !== 'element' || child.name !== 'resp') continue;
        const rid = child.attributes.id;
        if (typeof rid === 'string' && rid) assigned.add(rid);
      }
    }
    const orphans = Object.keys(respNames).filter((rid) => !assigned.has(rid));
    return (
      <section className="space-y-3">
        {orphans.length > 0 && (
          <div
            className="rounded-md border border-amber-500/60 bg-amber-950/30 px-3 py-2 text-sm text-amber-100"
            role="alert"
          >
            <div className="font-semibold">
              {orphans.length} responsibilit{orphans.length === 1 ? 'y' : 'ies'} not
              assigned to any component
            </div>
            <ul className="mt-1 space-y-0.5 m-0 pl-0 list-none">
              {orphans.map((rid) => (
                <li key={rid} className="font-mono text-xs text-amber-200">
                  <span className="text-amber-100">{respNames[rid]}</span>{' '}
                  <span className="text-amber-300/70">({rid})</span>
                </li>
              ))}
            </ul>
          </div>
        )}
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
    const purpose = findChildText(node, 'purpose') ?? '';
    const ownedInvariantsNode = findChild(node, 'owned-invariants');
    const invariants: string[] = ownedInvariantsNode
      ? ownedInvariantsNode.children
          .filter((c) => c.type === 'element' && c.name === 'invariant')
          .map((c) => textContent(c).trim())
          .filter(Boolean)
      : [];
    const primaryOperationsNode = findChild(node, 'primary-operations');
    const operations: string[] = primaryOperationsNode
      ? primaryOperationsNode.children
          .filter((c) => c.type === 'element' && c.name === 'operation')
          .map((c) => textContent(c).trim())
          .filter(Boolean)
      : [];
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
        {purpose && (
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">Purpose</div>
            <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">{purpose}</p>
          </div>
        )}
        {invariants.length > 0 && (
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">
              Owned invariants
            </div>
            <ul className="text-sm text-gray-300 space-y-0.5 m-0 pl-4 list-disc">
              {invariants.map((inv, i) => (
                <li key={i} className="whitespace-pre-wrap">{inv}</li>
              ))}
            </ul>
          </div>
        )}
        {operations.length > 0 && (
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">
              Primary operations
            </div>
            <ul className="text-sm text-gray-300 space-y-0.5 m-0 pl-4 list-disc">
              {operations.map((op, i) => (
                <li key={i} className="whitespace-pre-wrap">{op}</li>
              ))}
            </ul>
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
    purpose: () => null,
    'owned-invariants': () => null,
    invariant: () => null,
    'primary-operations': () => null,
    operation: () => null,
    // Labeled techspec sub-blocks consumed by the techspec renderer.
    runtime: () => null,
    persistence: () => null,
    'write-path': () => null,
    concurrency: () => null,
    testing: () => null,
    deploy: () => null,
    technologies: () => null,
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
