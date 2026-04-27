import { CollapsibleSection } from './CollapsibleSection';
import { Paragraphs } from './Paragraphs';
import type { XmlElement, XmlRendererMap } from './types';
import { findChild, findChildText, findChildren, textContent } from './types';

/**
 * Renderer overrides for the comparch schema:
 *
 *   <comparch>
 *     <technical-specification>…</technical-specification>
 *     <public-surface>…</public-surface>
 *     <private-surface>…</private-surface>
 *     <failure-surface>…</failure-surface>
 *     <policies><policy>…</policy>…</policies>
 *     <dependencies><dep to="comp_..."/></dependencies>
 *     <subcomponents>
 *       <subcomponent alias="...">
 *         <name>…</name>
 *         <purpose>…one sentence…</purpose>
 *         <owned-invariants><invariant>…</invariant>…</owned-invariants>
 *         <primary-operations><operation>…</operation>…</primary-operations>
 *         <responsibilities>…free-text prose…</responsibilities>
 *         <owns>
 *           <resp id="resp_..."><feat id="feat_..."/>…</resp>
 *           …
 *         </owns>
 *         [<foundation/>]
 *       </subcomponent>
 *       …
 *     </subcomponents>
 *     <sub-dependencies><dep from="alias1" to="alias2"/></sub-dependencies>
 *   </comparch>
 *
 * Eight sections: the four fragment sections render as prose
 * blocks, policies as cards, dependencies as a compact list,
 * subcomponents as a grid of cards (mirroring sysarch's
 * component cards minus the kind badge since it's inherited),
 * and sub-dependencies as an arrow list. Each subcomponent's
 * ``<owns>`` block surfaces its parent-resp + feat-slice claims
 * with names resolved from the structure snapshot.
 */

/**
 * Build a comparch renderer map with project-level lookups.
 *
 * - ``respNames``: top-level ``resp_*`` id → display name. Used by
 *   the per-subcomponent Owns section to render claimed parent
 *   responsibilities as ``Name (resp_id)`` instead of bare IDs.
 * - ``featureNames``: ``feat_*`` id → display name. Same idea for
 *   each per-resp feat-slice chip.
 *
 * Callers that don't need either map can use the default module-
 * level :data:`comparchRenderers` export (empty maps → bare IDs).
 */
export function makeComparchRenderers(
  respNames: Record<string, string> = {},
  featureNames: Record<string, string> = {},
): XmlRendererMap {
  const renderRespId = (rid: string) => {
    const name = respNames[rid];
    return name ? `${name} (${rid})` : rid;
  };
  const renderFeatId = (fid: string) => {
    const name = featureNames[fid];
    return name ? `${name} (${fid})` : fid;
  };

  return {
    ...comparchRenderers,
    subcomponent: (node) => renderSubcomponent(node, renderRespId, renderFeatId),
  };
}

interface OwnedClaim {
  respId: string;
  featIds: string[];
}

function parseOwns(node: XmlElement | null | undefined): OwnedClaim[] {
  if (!node) return [];
  const claims: OwnedClaim[] = [];
  for (const child of node.children) {
    if (child.type !== 'element' || child.name !== 'resp') continue;
    const id = child.attributes.id;
    if (typeof id !== 'string' || !id) continue;
    const featIds: string[] = [];
    for (const fchild of child.children) {
      if (fchild.type !== 'element' || fchild.name !== 'feat') continue;
      const fid = fchild.attributes.id;
      if (typeof fid === 'string' && fid) featIds.push(fid);
    }
    claims.push({ respId: id, featIds });
  }
  return claims;
}

function renderSubcomponent(
  node: XmlElement,
  renderRespId: (rid: string) => string,
  renderFeatId: (fid: string) => string,
) {
  const aliasAttr = node.attributes.alias;
  const alias = typeof aliasAttr === 'string' ? aliasAttr : '?';
  const name = findChildText(node, 'name') ?? 'Untitled';
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
  const isFoundation = node.children.some(
    (c) => c.type === 'element' && c.name === 'foundation',
  );
  const responsibilities = (findChildText(node, 'responsibilities') ?? '').trim();
  const ownsNode = findChild(node, 'owns');
  const claims = parseOwns(ownsNode);

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
      {purpose && (
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-wider text-gray-500">
            Purpose
          </div>
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
      {responsibilities && (
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-wider text-gray-500">
            Responsibilities
          </div>
          <p className="text-sm text-gray-300 m-0 whitespace-pre-wrap">
            {responsibilities}
          </p>
        </div>
      )}
      <div className="space-y-1">
        <div className="text-[10px] uppercase tracking-wider text-gray-500">
          Owns
        </div>
        {claims.length === 0 ? (
          <p className="text-xs text-gray-500 italic m-0">
            No parent-responsibility claims (foundation / internal plumbing).
          </p>
        ) : (
          <ul className="space-y-1 m-0 pl-0 list-none">
            {claims.map((claim) => (
              <li
                key={claim.respId}
                className="text-sm text-gray-300 flex flex-wrap items-baseline gap-x-2 gap-y-1"
              >
                <span className="font-mono text-xs text-gray-300">
                  {renderRespId(claim.respId)}
                </span>
                {claim.featIds.length > 0 ? (
                  <span className="flex flex-wrap gap-1">
                    {claim.featIds.map((fid) => (
                      <span
                        key={fid}
                        className="text-[10px] font-mono bg-gray-900/60 border border-gray-700 rounded px-1.5 py-0.5 text-gray-400"
                      >
                        {renderFeatId(fid)}
                      </span>
                    ))}
                  </span>
                ) : (
                  <span className="text-[10px] italic text-gray-500">
                    (whole resp, no feat slice)
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </CollapsibleSection>
  );
}

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

  'failure-surface': (node) => (
    <CollapsibleSection summary="Failure Surface">
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

  subcomponent: (node) =>
    renderSubcomponent(
      node,
      (rid) => rid,
      (fid) => fid,
    ),

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
  purpose: () => null,
  'owned-invariants': () => null,
  invariant: () => null,
  'primary-operations': () => null,
  operation: () => null,
  responsibilities: () => null,
  owns: () => null,
  resp: () => null,
  feat: () => null,
  foundation: () => null,
  trigger: () => null,
  required: () => null,
  rationale: () => null,
  dep: () => null,
};
