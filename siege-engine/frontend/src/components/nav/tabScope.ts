import type { StructureNode } from '../../api/structure';

/**
 * Derives contextual tabs for the workspace detail pane from the
 * currently-selected node. Three scopes:
 *
 * - **System** — selected node is expansion / reqs / sysarch.
 *   Tabs link across the three system-level pages.
 * - **Top-level component** — selected is a ``comp_*`` with
 *   ``parent_id === null`` or any of its child tiers (subreqs /
 *   fanin / un-fanned-out impl). Tabs cycle the comp's views:
 *   Overview (sysarch fragments), Subreqs, Comparch, Fanin (if
 *   present), Implementation (if present).
 * - **Subcomponent** — selected is a sub ``comp_*`` or its impl
 *   child. Tabs: Subcomparch, Implementation (if present).
 *
 * Active-tab resolution: for the component scope, a plain
 * ``?node=<compId>`` lands on Overview. Adding ``?view=comparch``
 * flips to the Comparch tab without changing the selected node —
 * the two share a node id but distinguish via the view param.
 * Other tabs each have their own child node id.
 */

import { SYNTHETIC_IDS } from './buildNavTree';

export type TabKey =
  | 'expansion'
  | 'reqs'
  | 'sysarch'
  | 'overview'
  | 'subreqs'
  | 'comparch'
  | 'fanin'
  | 'impl'
  | 'subcomparch'
  | 'sub-impl';

export interface Tab {
  key: TabKey;
  label: string;
  /** URL ``?node=`` target when this tab is clicked. */
  targetNodeId: string;
  /** URL ``?view=`` value — only set for the comp scope tabs
   *  that share a node id but differ in rendered view. */
  targetView?: 'overview' | 'comparch';
}

export interface TabScope {
  tabs: Tab[];
  activeKey: TabKey | null;
  /** Human-readable label for the breadcrumb header above the
   *  tabs (e.g. the component name). */
  scopeLabel: string | null;
}

const EMPTY_SCOPE: TabScope = { tabs: [], activeKey: null, scopeLabel: null };

const SYSTEM_TIERS = new Set(['expansion', 'reqs', 'sysarch']);

export function tabScope(
  selectedId: string | null,
  view: string | null,
  nodes: StructureNode[],
): TabScope {
  if (!selectedId) return EMPTY_SCOPE;
  // Synthetic entries (vocab / refs / decomposition graph) don't
  // carry tabs — they're leaf views the sidebar hops into directly.
  if (
    selectedId === SYNTHETIC_IDS.VOCABULARY ||
    selectedId === SYNTHETIC_IDS.REFERENCES ||
    selectedId === SYNTHETIC_IDS.DAG ||
    selectedId === SYNTHETIC_IDS.QUEUE ||
    selectedId === SYNTHETIC_IDS.MAP_FEAT_RESP ||
    selectedId === SYNTHETIC_IDS.COMPONENTS_ROOT
  ) {
    return EMPTY_SCOPE;
  }

  const selected = nodes.find((n) => n.id === selectedId) ?? null;
  if (!selected) return EMPTY_SCOPE;

  if (SYSTEM_TIERS.has(selected.tier)) {
    return {
      tabs: systemTabs(nodes),
      activeKey: selected.tier as TabKey,
      scopeLabel: 'System',
    };
  }

  const ownerComp = findOwnerComp(selected, nodes);
  if (!ownerComp) return EMPTY_SCOPE;

  if (ownerComp.parent_id === null) {
    return {
      tabs: topLevelCompTabs(ownerComp, nodes),
      activeKey: activeKeyForTopLevel(selected, view, ownerComp),
      scopeLabel: ownerComp.name,
    };
  }
  return {
    tabs: subcompTabs(ownerComp, nodes),
    activeKey: activeKeyForSubcomp(selected, ownerComp),
    scopeLabel: ownerComp.name,
  };
}

function systemTabs(nodes: StructureNode[]): Tab[] {
  const tabs: Tab[] = [];
  const exp = nodes.find((n) => n.tier === 'expansion');
  if (exp) tabs.push({ key: 'expansion', label: 'Feature Expansion', targetNodeId: exp.id });
  const reqs = nodes.find((n) => n.tier === 'reqs');
  if (reqs) tabs.push({ key: 'reqs', label: 'Requirements', targetNodeId: reqs.id });
  const sys = nodes.find((n) => n.tier === 'sysarch');
  if (sys) tabs.push({ key: 'sysarch', label: 'Sysarch', targetNodeId: sys.id });
  return tabs;
}

function findOwnerComp(
  selected: StructureNode,
  nodes: StructureNode[],
): StructureNode | null {
  if (selected.tier === 'comp') return selected;
  // Child tiers of a comp carry parent_id pointing at it.
  if (selected.tier === 'subreqs' || selected.tier === 'fanin' || selected.tier === 'impl') {
    if (!selected.parent_id) return null;
    const parent = nodes.find((n) => n.id === selected.parent_id);
    if (!parent || parent.tier !== 'comp') return null;
    return parent;
  }
  return null;
}

function topLevelCompTabs(comp: StructureNode, nodes: StructureNode[]): Tab[] {
  const tabs: Tab[] = [
    { key: 'overview', label: 'Overview', targetNodeId: comp.id, targetView: 'overview' },
  ];
  const subreqs = nodes.find((n) => n.tier === 'subreqs' && n.parent_id === comp.id);
  if (subreqs) tabs.push({ key: 'subreqs', label: 'Subrequirements', targetNodeId: subreqs.id });
  tabs.push({
    key: 'comparch',
    label: 'Comparch',
    targetNodeId: comp.id,
    targetView: 'comparch',
  });
  const fanin = nodes.find((n) => n.tier === 'fanin' && n.parent_id === comp.id);
  if (fanin) tabs.push({ key: 'fanin', label: 'Fan-in', targetNodeId: fanin.id });
  const topLevelImpl = nodes.find((n) => n.tier === 'impl' && n.parent_id === comp.id);
  if (topLevelImpl) {
    tabs.push({ key: 'impl', label: 'Implementation', targetNodeId: topLevelImpl.id });
  }
  return tabs;
}

function subcompTabs(sub: StructureNode, nodes: StructureNode[]): Tab[] {
  const tabs: Tab[] = [
    { key: 'subcomparch', label: 'Subcomparch', targetNodeId: sub.id },
  ];
  const impl = nodes.find((n) => n.tier === 'impl' && n.parent_id === sub.id);
  if (impl) tabs.push({ key: 'sub-impl', label: 'Implementation', targetNodeId: impl.id });
  return tabs;
}

function activeKeyForTopLevel(
  selected: StructureNode,
  view: string | null,
  comp: StructureNode,
): TabKey {
  if (selected.id === comp.id) {
    return view === 'comparch' ? 'comparch' : 'overview';
  }
  if (selected.tier === 'subreqs') return 'subreqs';
  if (selected.tier === 'fanin') return 'fanin';
  if (selected.tier === 'impl') return 'impl';
  return 'overview';
}

function activeKeyForSubcomp(selected: StructureNode, sub: StructureNode): TabKey {
  if (selected.id === sub.id) return 'subcomparch';
  if (selected.tier === 'impl') return 'sub-impl';
  return 'subcomparch';
}
