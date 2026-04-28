// Tier-filter helpers shared by FullDagView and
// ComponentDecompositionPanel.
//
// The DAG element list uses fine-grained NodeType values (feat,
// resp-top, comp-top, comp-sub, fanin, impl, external-feat, …)
// because the two views render different shapes for what is
// semantically the same tier (e.g. ``feat`` in the top-level view
// and ``external-feat`` in the drill view both represent a
// feature). Users think in tier terms, not type terms, so the
// chip row collapses related types under a single
// ``TierGroupKey``.
//
// State persistence: the wrapper writes the hidden-group set into
// the URL as ``?hide=features,responsibilities`` so refreshes
// and shared links preserve the view.

import type { ElementDefinition } from 'cytoscape';
import type { NodeType } from './elements';

export type TierGroupKey =
  | 'features'
  | 'responsibilities'
  | 'policies'
  | 'local-policies'
  | 'components'
  | 'subcomponents'
  | 'fanin'
  | 'implementations';

interface TierGroupSpec {
  key: TierGroupKey;
  /** Chip label shown to the user. */
  label: string;
  /** NodeType values that map to this group. Multiple types per
   *  group is the norm — top-level and drill views encode the same
   *  tier under different type names. */
  types: NodeType[];
}

// Order is the chip-row presentation order. Roughly upstream-to-
// downstream (features → impls), with the cross-cutting policy
// groups slotted near where they conceptually attach.
const TIER_GROUPS: TierGroupSpec[] = [
  {
    key: 'features',
    label: 'Features',
    types: ['feat', 'external-feat'],
  },
  {
    key: 'responsibilities',
    label: 'Responsibilities',
    types: ['resp-top', 'external-resp'],
  },
  {
    key: 'policies',
    label: 'Top-level policies',
    types: ['policy-top', 'external-policy'],
  },
  {
    key: 'local-policies',
    label: 'Local policies',
    types: ['policy-local'],
  },
  {
    key: 'components',
    label: 'Components',
    types: ['comp-top'],
  },
  {
    key: 'subcomponents',
    label: 'Subcomponents',
    types: ['comp-sub'],
  },
  {
    key: 'fanin',
    label: 'Fan-in',
    types: ['fanin'],
  },
  {
    key: 'implementations',
    label: 'Implementations',
    types: ['impl'],
  },
];

const KEY_TO_SPEC: Record<TierGroupKey, TierGroupSpec> = TIER_GROUPS.reduce(
  (acc, spec) => {
    acc[spec.key] = spec;
    return acc;
  },
  {} as Record<TierGroupKey, TierGroupSpec>,
);

const ALL_KEYS: ReadonlySet<TierGroupKey> = new Set(
  TIER_GROUPS.map((g) => g.key),
);

export interface AvailableGroup {
  key: TierGroupKey;
  label: string;
}

/** Walk the element list and return the chip-row order of groups
 *  that have at least one node present. Empty groups are dropped
 *  so users don't see chips that toggle nothing. */
export function availableGroups(
  elements: ElementDefinition[],
): AvailableGroup[] {
  const presentTypes = new Set<string>();
  for (const el of elements) {
    const t = (el.data ?? {}).type;
    if (typeof t === 'string') presentTypes.add(t);
  }
  return TIER_GROUPS.filter((spec) =>
    spec.types.some((t) => presentTypes.has(t)),
  ).map((spec) => ({ key: spec.key, label: spec.label }));
}

/** Expand a set of group keys into the underlying ``NodeType``
 *  set. Used by DagCanvas to apply the ``.hidden`` class to the
 *  right nodes. */
export function expandToTypes(
  groupKeys: ReadonlySet<TierGroupKey>,
): Set<NodeType> {
  const out = new Set<NodeType>();
  for (const key of groupKeys) {
    const spec = KEY_TO_SPEC[key];
    if (!spec) continue;
    for (const t of spec.types) out.add(t);
  }
  return out;
}

/** Parse the ``?hide=`` URL value. Unknown keys silently dropped
 *  so an old URL with a renamed key doesn't blow up. */
export function parseHiddenParam(value: string | null): Set<TierGroupKey> {
  if (!value) return new Set();
  const out = new Set<TierGroupKey>();
  for (const raw of value.split(',')) {
    const trimmed = raw.trim();
    if (ALL_KEYS.has(trimmed as TierGroupKey)) {
      out.add(trimmed as TierGroupKey);
    }
  }
  return out;
}

/** Serialize a hidden-group set back into the URL value. Returns
 *  ``null`` for an empty set so the caller can ``delete`` the
 *  param entirely. */
export function serializeHiddenParam(
  hidden: ReadonlySet<TierGroupKey>,
): string | null {
  if (hidden.size === 0) return null;
  // Stable order matches the chip-row order so toggling one chip
  // produces a deterministic URL.
  const ordered = TIER_GROUPS.filter((g) => hidden.has(g.key)).map(
    (g) => g.key,
  );
  return ordered.join(',');
}
