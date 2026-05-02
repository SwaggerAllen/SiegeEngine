import type { StructureEdge, StructureNode } from '../../api/structure';

/**
 * Topologically sort top-level comps by ``dependency`` and
 * ``domain_parent`` edges so dependencies and domain parents
 * appear before their dependents. A presentational comp's
 * comparch can't run until its domain parents have populated
 * fan-ins (see CLAUDE.md scheduling invariants), so domain_parent
 * is a real ordering constraint, not just a scheduling gate.
 *
 * Kahn's algorithm with a (is_foundation desc, display_order asc,
 * id) tiebreak inside each frontier so the rendered order is
 * stable across regenerations and foundations land at the very
 * top.
 *
 * Cycles (sysarch validator should reject these, but
 * defence-in-depth) get appended in display_order at the end so
 * no comp is dropped from the rendered list.
 */
const ORDERING_EDGE_TYPES: ReadonlySet<string> = new Set([
  'dependency',
  'domain_parent',
]);

export function topoSortComps(
  comps: StructureNode[],
  edges: ReadonlyArray<StructureEdge>,
): StructureNode[] {
  const compIds = new Set(comps.map((c) => c.id));
  const compById = new Map(comps.map((c) => [c.id, c]));
  const dependsOnCount = new Map<string, number>();
  // For each comp, the comps that have an outbound dep pointing at it
  // (i.e. comps that need to be decremented when this one ships).
  const dependents = new Map<string, string[]>();
  for (const c of comps) {
    dependsOnCount.set(c.id, 0);
    dependents.set(c.id, []);
  }
  // Dedup (source, target) pairs so a comp with both a `dependency`
  // and a `domain_parent` edge to the same target only counts once.
  const seenEdges = new Set<string>();
  for (const e of edges) {
    if (!ORDERING_EDGE_TYPES.has(e.edge_type)) continue;
    if (!compIds.has(e.source_id) || !compIds.has(e.target_id)) continue;
    const key = `${e.source_id}->${e.target_id}`;
    if (seenEdges.has(key)) continue;
    seenEdges.add(key);
    dependsOnCount.set(e.source_id, (dependsOnCount.get(e.source_id) ?? 0) + 1);
    dependents.get(e.target_id)?.push(e.source_id);
  }

  const tiebreak = (a: StructureNode, b: StructureNode) => {
    // Foundations first within a tie.
    const aFound = (a as { is_foundation?: boolean }).is_foundation ? 1 : 0;
    const bFound = (b as { is_foundation?: boolean }).is_foundation ? 1 : 0;
    if (aFound !== bFound) return bFound - aFound;
    if (a.display_order !== b.display_order) {
      return a.display_order - b.display_order;
    }
    return a.id.localeCompare(b.id);
  };

  const frontier: StructureNode[] = comps
    .filter((c) => dependsOnCount.get(c.id) === 0)
    .sort(tiebreak);
  const result: StructureNode[] = [];
  const seen = new Set<string>();
  while (frontier.length > 0) {
    const next = frontier.shift()!;
    if (seen.has(next.id)) continue;
    seen.add(next.id);
    result.push(next);
    for (const depId of dependents.get(next.id) ?? []) {
      const remaining = (dependsOnCount.get(depId) ?? 0) - 1;
      dependsOnCount.set(depId, remaining);
      if (remaining === 0) {
        const dep = compById.get(depId);
        if (dep && !seen.has(dep.id)) {
          frontier.push(dep);
          frontier.sort(tiebreak);
        }
      }
    }
  }
  // Fallback for cycles — append leftovers in stable display order.
  for (const c of comps) {
    if (!seen.has(c.id)) result.push(c);
  }
  return result;
}
