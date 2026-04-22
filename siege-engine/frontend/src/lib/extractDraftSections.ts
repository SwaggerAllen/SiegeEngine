import { parseXml } from '../components/xml';
import {
  findChild,
  findChildText,
  findChildren,
} from '../components/xml/types';
import type { XmlElement, XmlNode } from '../components/xml/types';

/**
 * Section-aware parsing helpers for the three structured bootstrap
 * docs (expansion, requirements, sysarch).
 *
 * Used by :component:`StructuredDraftDiffView` to break a draft
 * into navigable per-entity sections (one feature / one
 * responsibility / one component), so diffs render as "what
 * changed in Billing" rather than as a wall of XML line changes.
 * Keyed by whichever attribute reliably identifies the entity:
 *
 * * expansion: feature ``<name>`` (no stable id attribute exists
 *   yet in the bootstrap draft — rename surfaces as remove+add,
 *   which is usually what the user wants to see anyway).
 * * requirements: responsibility ``<name>``.
 * * sysarch: component ``alias=`` attribute (stable during a
 *   single draft lifecycle; the sysarch prompt treats the alias
 *   as identity).
 *
 * Callers fall back to :component:`DraftDiffView` when this helper
 * returns ``null`` — the doc isn't one of the structured kinds,
 * or parsing failed. Callers also fall back to the unstructured
 * view when the section list is empty or only one side has
 * sections.
 */

export type DraftDocKind = 'expansion' | 'requirements' | 'sysarch';

export interface DraftSection {
  /** Stable identifier used to pair before/after across a diff. */
  key: string;
  /** Human-readable label shown in the accordion header. */
  label: string;
  /**
   * Entity kind — ``"feature"`` / ``"responsibility"`` /
   * ``"component"`` / ``"techspec"`` / ``"policies"``. The UI
   * uses this to pick a tier-appropriate label prefix.
   */
  kind: string;
  /** Raw XML for just this section; fed to :component:`DraftDiffView`. */
  xml: string;
}

export function extractDraftSections(
  xml: string | null | undefined,
  docKind: DraftDocKind,
): DraftSection[] | null {
  if (!xml || !xml.trim()) return null;
  let root: XmlElement;
  try {
    // Bootstrap drafts commonly emit sibling top-level tags —
    // e.g. ``<introduction>…</introduction><requirements>…</requirements>``
    // — which ``parseXml`` would treat as multiple roots and only
    // return the first one from. Wrap in a synthetic root so every
    // sibling survives as a child of the wrapper and downstream
    // ``findTagInTree`` walks them all.
    root = parseXml(`<__draft__>${xml}</__draft__>`);
  } catch {
    return null;
  }
  if (docKind === 'expansion') {
    const features = findFeaturesContainer(root);
    if (!features) return null;
    return featureSections(features);
  }
  if (docKind === 'requirements') {
    const reqs = findTagInTree(root, 'requirements');
    if (!reqs) return null;
    return findChildren(reqs, 'responsibility').map((r, i) => ({
      key: sectionKey(findChildText(r, 'name'), 'resp', i),
      label: findChildText(r, 'name') ?? `Responsibility ${i + 1}`,
      kind: 'responsibility',
      xml: serializeElement(r),
    }));
  }
  if (docKind === 'sysarch') {
    const sections = sysarchSections(root);
    return sections.length === 0 ? null : sections;
  }
  return null;
}

// ── Per-kind extractors ──────────────────────────────────────────

function findFeaturesContainer(root: XmlElement): XmlElement | null {
  return findTagInTree(root, 'features');
}

function featureSections(features: XmlElement): DraftSection[] {
  const out: DraftSection[] = [];
  let idx = 0;
  for (const child of features.children) {
    if (child.type !== 'element') continue;
    if (child.name === 'feature') {
      out.push(featureToSection(child, idx++));
    } else if (child.name === 'group') {
      // Groups are categorical headings — unroll to their feature
      // children so the diff pairs on actual features, not on the
      // group wrapper (which rarely changes meaningfully).
      for (const feat of findChildren(child, 'feature')) {
        out.push(featureToSection(feat, idx++));
      }
    }
  }
  return out;
}

function featureToSection(el: XmlElement, order: number): DraftSection {
  const name = findChildText(el, 'name');
  return {
    key: sectionKey(name, 'feat', order),
    label: name ?? `Feature ${order + 1}`,
    kind: 'feature',
    xml: serializeElement(el),
  };
}

function sysarchSections(root: XmlElement): DraftSection[] {
  const sysarch = findTagInTree(root, 'sysarch');
  if (!sysarch) return [];
  const out: DraftSection[] = [];
  for (const child of sysarch.children) {
    if (child.type !== 'element') continue;
    if (child.name === 'components') {
      // Break the components block into per-component sections so
      // the diff shows "what changed in BillingService" rather than
      // a single giant block.
      const comps = findChildren(child, 'component');
      comps.forEach((comp, i) => {
        const alias = typeof comp.attributes.alias === 'string'
          ? comp.attributes.alias
          : undefined;
        const name = findChildText(comp, 'name');
        out.push({
          key: sectionKey(alias ?? name, 'comp', i),
          label: name ?? alias ?? `Component ${i + 1}`,
          kind: 'component',
          xml: serializeElement(comp),
        });
      });
    } else {
      // Other top-level sysarch children (techspec, policies,
      // dependencies, etc.) go through as single sections so the
      // user can see tech-stack or policy drift as distinct
      // entries.
      out.push({
        key: `section:${child.name}`,
        label: humanizeTag(child.name),
        kind: child.name,
        xml: serializeElement(child),
      });
    }
  }
  return out;
}

// ── Shared helpers ───────────────────────────────────────────────

/**
 * Find an element by name anywhere in the tree — the bootstrap
 * root element varies by tier (e.g. ``<expansion>``, ``<reqs>``,
 * or a bare ``<features>`` for legacy content) so the extractor
 * can't assume it lives at a known depth.
 */
function findTagInTree(root: XmlElement, name: string): XmlElement | null {
  if (root.name === name) return root;
  const direct = findChild(root, name);
  if (direct) return direct;
  for (const child of root.children) {
    if (child.type !== 'element') continue;
    const found = findTagInTree(child, name);
    if (found) return found;
  }
  return null;
}

function sectionKey(
  identifier: string | undefined,
  prefix: string,
  order: number,
): string {
  const trimmed = (identifier ?? '').trim();
  if (trimmed) return `${prefix}:${trimmed.toLowerCase()}`;
  // Fallback: order-based key. Diffs across a renumbering will
  // mispair, but that's the same shape as no-identifier inputs in
  // the worst case.
  return `${prefix}:__idx_${order}__`;
}

function humanizeTag(name: string): string {
  return name
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Serialize an :class:`XmlElement` back to an XML string.
 *
 * Not a fully-escaped serializer — it trusts the input came from
 * :func:`parseXml` over LLM-generated docs and writes plain angle-
 * bracket output. Good enough for the diff view's consumption
 * (the diff engine works on text).
 */
function serializeElement(node: XmlNode): string {
  if (node.type === 'text') return node.value;
  const attrs = Object.entries(node.attributes)
    .map(([k, v]) =>
      v === true ? ` ${k}` : ` ${k}="${escapeAttr(String(v))}"`,
    )
    .join('');
  if (node.children.length === 0) {
    return `<${node.name}${attrs}/>`;
  }
  const inner = node.children.map(serializeElement).join('');
  return `<${node.name}${attrs}>${inner}</${node.name}>`;
}

function escapeAttr(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}
