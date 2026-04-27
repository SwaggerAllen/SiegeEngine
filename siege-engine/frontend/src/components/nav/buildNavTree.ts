import type { StructureEdge, StructureNode } from '../../api/structure';
import { topoSortComps } from './topoSortComps';

/**
 * A single item in the rendered sidebar tree.
 *
 * Real nodes (tier='comp', 'impl', 'fanin', etc.) carry a
 * ``node`` payload and a concrete id from the backend. Synthetic
 * items (section headers like "Components", "Vocabulary") have
 * ``node === null`` and use a stable colon-prefixed id that
 * cannot collide with backend node ids (backend ids use
 * underscores).
 *
 * Children are pre-sorted by the assembly logic — consumers
 * render them in order without further sorting.
 */
export interface NavItem {
  id: string;
  label: string;
  /** Real node data if backed by a DB row, null for synthetic entries. */
  node: StructureNode | null;
  /** Short role tag used for styling dispatch (icon + colour). */
  role:
    | 'expansion'
    | 'reqs'
    | 'sysarch'
    | 'vocabulary'
    | 'references'
    | 'dag'
    | 'queue'
    | 'tier-ops'
    | 'debug'
    | 'edit-root'
    | 'edit-dependencies'
    | 'edit-domain-parents'
    | 'edit-decomposition'
    | 'edit-feat-resp'
    | 'edit-resp-comp'
    | 'components-root'
    | 'component-top'
    | 'component-sub'
    | 'component-fanin'
    | 'component-impl'
    | 'subcomponent-impl';
  children: NavItem[];
  /** Pre-aggregated status for the badge cluster on this row. */
  status: {
    has_pending_draft: boolean;
    generation_running: boolean;
    has_error: boolean;
    needs_user_action: boolean;
    /** Phase 9 — this node has one or more active upstream staleness markers. */
    is_stale: boolean;
    /** True if this item or any descendant has a pending draft. */
    descendant_has_pending_draft: boolean;
    /** True if any descendant has generation running (for the collapsed pulse). */
    descendant_generation_running: boolean;
    /** True if any descendant has an errored latest job (for the collapsed red dot). */
    descendant_has_error: boolean;
    /** True if any descendant has a cancelled latest job (for the collapsed blue dot). */
    descendant_needs_user_action: boolean;
    /** True if any descendant is stale (for the collapsed stale dot). */
    descendant_is_stale: boolean;
  };
}

/**
 * Stable synthetic item ids. Colon prefix guarantees they can
 * never collide with backend-minted node ids, which use
 * Crockford base32 with underscores.
 */
export const SYNTHETIC_IDS = {
  VOCABULARY: ':vocabulary',
  REFERENCES: ':references',
  // Phase 10 replaces the old narrow decomposition-graph view with
  // the full layered DAG. Kept the user-facing label "Decomposition
  // Graph" for continuity; the synthetic id reads `:dag` internally.
  DAG: ':dag',
  // Phase 11 — the pending-change queue panel.
  QUEUE: ':queue',
  // Tier ops — bulk reset / bulk AI-review per tier.
  TIER_OPS: ':tier-ops',
  // Debug snapshot — copy project state + recent events/jobs.
  DEBUG: ':debug',
  // Phase 11 structured-edit UIs. Each synthetic id routes to a
  // dedicated editor page in NavDetail.
  EDIT_ROOT: ':edit',
  EDIT_DEPS: ':edit-dependencies',
  EDIT_DOMAIN_PARENTS: ':edit-domain-parents',
  EDIT_DECOMPOSITION: ':edit-decomposition',
  EDIT_FEAT_RESP: ':edit-feat-resp',
  EDIT_RESP_COMP: ':edit-resp-comp',
  COMPONENTS_ROOT: ':components',
} as const;

const EMPTY_STATUS = {
  has_pending_draft: false,
  generation_running: false,
  has_error: false,
  needs_user_action: false,
  is_stale: false,
  descendant_has_pending_draft: false,
  descendant_generation_running: false,
  descendant_has_error: false,
  descendant_needs_user_action: false,
  descendant_is_stale: false,
};

function singleNode(
  nodes: StructureNode[],
  predicate: (n: StructureNode) => boolean,
): StructureNode | undefined {
  return nodes.find(predicate);
}

function statusFor(n: StructureNode) {
  return {
    has_pending_draft: n.has_pending_draft,
    generation_running: n.generation_running,
    has_error: n.has_error,
    needs_user_action: n.needs_user_action,
    is_stale: n.is_stale,
    descendant_has_pending_draft: n.has_pending_draft,
    descendant_generation_running: n.generation_running,
    descendant_has_error: n.has_error,
    descendant_needs_user_action: n.needs_user_action,
    descendant_is_stale: n.is_stale,
  };
}

function rollUpStatus(self: NavItem['status'], children: NavItem[]): NavItem['status'] {
  let descPending = self.has_pending_draft;
  let descRunning = self.generation_running;
  let descError = self.has_error;
  let descCancelled = self.needs_user_action;
  let descStale = self.is_stale;
  for (const c of children) {
    if (c.status.descendant_has_pending_draft) descPending = true;
    if (c.status.descendant_generation_running) descRunning = true;
    if (c.status.descendant_has_error) descError = true;
    if (c.status.descendant_needs_user_action) descCancelled = true;
    if (c.status.descendant_is_stale) descStale = true;
  }
  return {
    ...self,
    descendant_has_pending_draft: descPending,
    descendant_generation_running: descRunning,
    descendant_has_error: descError,
    descendant_needs_user_action: descCancelled,
    descendant_is_stale: descStale,
  };
}

/**
 * Assemble the flat backend response into the hierarchical shape
 * the sidebar renders. Pure function — same input always produces
 * the same output tree.
 *
 * Layout (top to bottom):
 *   Feature Expansion  (present only if a node exists)
 *   Requirements       (same)
 *   Sysarch            (same)
 *   Vocabulary         (synthetic, always)
 *   References         (synthetic, always)
 *   Decomposition      (synthetic, always — opens the cytoscape view)
 *   Components/        (synthetic header, always shown once sysarch has minted any top-level comp)
 *     [each top-level comp]
 *       Subrequirements  (node, if exists)
 *       Fan-in           (node, if exists)
 *       Implementation   (if comp has an impl child — only for un-fanned-out comps)
 *       [each subcomponent]
 *         Implementation (if sub has an impl child)
 */
export function buildNavTree(
  nodes: StructureNode[],
  edges: ReadonlyArray<StructureEdge> = [],
): NavItem[] {
  const items: NavItem[] = [];

  const expansion = singleNode(nodes, (n) => n.tier === 'expansion');
  if (expansion) {
    items.push({
      id: expansion.id,
      label: 'Feature Expansion',
      node: expansion,
      role: 'expansion',
      children: [],
      status: statusFor(expansion),
    });
  }
  const reqs = singleNode(nodes, (n) => n.tier === 'reqs');
  if (reqs) {
    items.push({
      id: reqs.id,
      label: 'Requirements',
      node: reqs,
      role: 'reqs',
      children: [],
      status: statusFor(reqs),
    });
  }
  const sysarch = singleNode(nodes, (n) => n.tier === 'sysarch');
  if (sysarch) {
    items.push({
      id: sysarch.id,
      label: 'Sysarch',
      node: sysarch,
      role: 'sysarch',
      children: [],
      status: statusFor(sysarch),
    });
  }

  items.push({
    id: SYNTHETIC_IDS.VOCABULARY,
    label: 'Vocabulary',
    node: null,
    role: 'vocabulary',
    children: [],
    status: { ...EMPTY_STATUS },
  });
  items.push({
    id: SYNTHETIC_IDS.REFERENCES,
    label: 'References',
    node: null,
    role: 'references',
    children: [],
    status: { ...EMPTY_STATUS },
  });
  items.push({
    id: SYNTHETIC_IDS.DAG,
    label: 'Decomposition Graph',
    node: null,
    role: 'dag',
    children: [],
    status: { ...EMPTY_STATUS },
  });
  items.push({
    id: SYNTHETIC_IDS.QUEUE,
    label: 'Pending Changes',
    node: null,
    role: 'queue',
    children: [],
    status: { ...EMPTY_STATUS },
  });
  items.push({
    id: SYNTHETIC_IDS.TIER_OPS,
    label: 'Tier Ops',
    node: null,
    role: 'tier-ops',
    children: [],
    status: { ...EMPTY_STATUS },
  });
  items.push({
    id: SYNTHETIC_IDS.DEBUG,
    label: 'Debug Snapshot',
    node: null,
    role: 'debug',
    children: [],
    status: { ...EMPTY_STATUS },
  });
  items.push({
    id: SYNTHETIC_IDS.EDIT_ROOT,
    label: 'Edit',
    node: null,
    role: 'edit-root',
    children: [
      {
        id: SYNTHETIC_IDS.EDIT_FEAT_RESP,
        label: 'Features → Responsibilities',
        node: null,
        role: 'edit-feat-resp',
        children: [],
        status: { ...EMPTY_STATUS },
      },
      {
        id: SYNTHETIC_IDS.EDIT_RESP_COMP,
        label: 'Responsibilities → Components',
        node: null,
        role: 'edit-resp-comp',
        children: [],
        status: { ...EMPTY_STATUS },
      },
      {
        id: SYNTHETIC_IDS.EDIT_DECOMPOSITION,
        label: 'Decomposition',
        node: null,
        role: 'edit-decomposition',
        children: [],
        status: { ...EMPTY_STATUS },
      },
      {
        id: SYNTHETIC_IDS.EDIT_DEPS,
        label: 'Dependencies',
        node: null,
        role: 'edit-dependencies',
        children: [],
        status: { ...EMPTY_STATUS },
      },
      {
        id: SYNTHETIC_IDS.EDIT_DOMAIN_PARENTS,
        label: 'Domain Parents',
        node: null,
        role: 'edit-domain-parents',
        children: [],
        status: { ...EMPTY_STATUS },
      },
    ],
    status: { ...EMPTY_STATUS },
  });

  // Top-level components + their subtrees.
  const topLevelComps = topoSortComps(
    nodes.filter((n) => n.tier === 'comp' && n.parent_id === null),
    edges,
  );

  if (topLevelComps.length > 0) {
    const componentItems: NavItem[] = topLevelComps.map((comp) =>
      buildComponentSubtree(comp, nodes),
    );
    const componentsRoot: NavItem = {
      id: SYNTHETIC_IDS.COMPONENTS_ROOT,
      label: 'Components',
      node: null,
      role: 'components-root',
      children: componentItems,
      status: { ...EMPTY_STATUS },
    };
    componentsRoot.status = rollUpStatus(componentsRoot.status, componentItems);
    items.push(componentsRoot);
  }

  return items;
}

function buildComponentSubtree(comp: StructureNode, nodes: StructureNode[]): NavItem {
  const children: NavItem[] = [];

  // Fan-in — a singleton fanin_* node parented to the comp (only
  // exists for fanned-out domain comps).
  const fanin = nodes.find((n) => n.tier === 'fanin' && n.parent_id === comp.id);
  if (fanin) {
    children.push({
      id: fanin.id,
      label: 'Fan-in',
      node: fanin,
      role: 'component-fanin',
      children: [],
      status: statusFor(fanin),
    });
  }

  // Implementation directly under an un-fanned-out top-level comp.
  const topLevelImpl = nodes.find((n) => n.tier === 'impl' && n.parent_id === comp.id);
  if (topLevelImpl) {
    children.push({
      id: topLevelImpl.id,
      label: 'Implementation',
      node: topLevelImpl,
      role: 'component-impl',
      children: [],
      status: statusFor(topLevelImpl),
    });
  }

  // Subcomponents + their leaves.
  const subs = nodes
    .filter((n) => n.tier === 'comp' && n.parent_id === comp.id)
    .sort((a, b) => a.display_order - b.display_order);
  for (const sub of subs) {
    const subChildren: NavItem[] = [];
    const subImpl = nodes.find((n) => n.tier === 'impl' && n.parent_id === sub.id);
    if (subImpl) {
      subChildren.push({
        id: subImpl.id,
        label: 'Implementation',
        node: subImpl,
        role: 'subcomponent-impl',
        children: [],
        status: statusFor(subImpl),
      });
    }
    const subItem: NavItem = {
      id: sub.id,
      label: sub.name,
      node: sub,
      role: 'component-sub',
      children: subChildren,
      status: statusFor(sub),
    };
    subItem.status = rollUpStatus(subItem.status, subChildren);
    children.push(subItem);
  }

  const compItem: NavItem = {
    id: comp.id,
    label: comp.name,
    node: comp,
    role: 'component-top',
    children,
    status: statusFor(comp),
  };
  compItem.status = rollUpStatus(compItem.status, children);
  return compItem;
}

/** Flatten a tree back out (for default-expand sets, tests, etc.). */
export function walkItems(items: NavItem[]): NavItem[] {
  const out: NavItem[] = [];
  for (const it of items) {
    out.push(it);
    out.push(...walkItems(it.children));
  }
  return out;
}

/**
 * The ids whose expand state defaults to open on first render.
 * Components root is always open so the comp list is visible
 * without clicking. Individual comps stay collapsed — user picks
 * which subtree to expand.
 */
export function defaultExpandedIds(): Set<string> {
  // Components root always opens so the comp list is visible
  // without an extra click. Individual comps stay collapsed —
  // the user picks which subtree to expand. Ancestor expansion
  // for a selected-via-URL node is handled in the layout hook.
  const open = new Set<string>();
  open.add(SYNTHETIC_IDS.COMPONENTS_ROOT);
  return open;
}

/** Given a selected id, return every ancestor id so the layout can auto-expand them. */
export function ancestorIds(items: NavItem[], selectedId: string | null): Set<string> {
  const out = new Set<string>();
  if (!selectedId) return out;
  const path: string[] = [];
  const dfs = (nodes: NavItem[]): boolean => {
    for (const n of nodes) {
      path.push(n.id);
      if (n.id === selectedId) return true;
      if (dfs(n.children)) return true;
      path.pop();
    }
    return false;
  };
  if (dfs(items)) {
    // Every id in the path except the selected leaf.
    for (const id of path.slice(0, -1)) out.add(id);
  }
  return out;
}
