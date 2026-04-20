import { useEffect, useMemo, useState } from 'react';
import type { StructureNode } from '../../api/structure';
import {
  ancestorIds,
  buildNavTree,
  defaultExpandedIds,
  SYNTHETIC_IDS,
  type NavItem,
} from './buildNavTree';

interface Props {
  nodes: StructureNode[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Invoked when the user taps a leaf node on mobile (closes the drawer). */
  onLeafSelect?: () => void;
}

/**
 * The sidebar tree. Pure render given the flat node list + a
 * selected id. Expand/collapse state lives here (useState) with
 * two overrides: ``defaultExpandedIds`` on mount + auto-expand
 * every ancestor of the current selection so deep-linking lands
 * the user on an already-visible row.
 */
export function NavTree({ nodes, selectedId, onSelect, onLeafSelect }: Props) {
  const items = useMemo(() => buildNavTree(nodes), [nodes]);
  const [expanded, setExpanded] = useState<Set<string>>(() => defaultExpandedIds());

  // Keep ancestors of the selected node expanded. This runs after
  // initial mount and whenever the selection changes.
  useEffect(() => {
    const ancestors = ancestorIds(items, selectedId);
    if (ancestors.size === 0) return;
    setExpanded((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const id of ancestors) {
        if (!next.has(id)) {
          next.add(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [items, selectedId]);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSelect = (item: NavItem) => {
    onSelect(item.id);
    if (item.children.length === 0 && onLeafSelect) onLeafSelect();
  };

  return (
    <ul
      role="tree"
      aria-label="Project navigation"
      className="space-y-0.5 text-sm"
    >
      {items.map((item) => (
        <NavTreeRow
          key={item.id}
          item={item}
          depth={0}
          selectedId={selectedId}
          expanded={expanded}
          onToggle={toggle}
          onSelect={handleSelect}
        />
      ))}
    </ul>
  );
}

interface RowProps {
  item: NavItem;
  depth: number;
  selectedId: string | null;
  expanded: Set<string>;
  onToggle: (id: string) => void;
  onSelect: (item: NavItem) => void;
}

function NavTreeRow({
  item,
  depth,
  selectedId,
  expanded,
  onToggle,
  onSelect,
}: RowProps) {
  const hasChildren = item.children.length > 0;
  const isExpanded = expanded.has(item.id);
  const isSelected = selectedId === item.id;
  // Components root is a section header, not a selectable detail
  // pane. Same for the synthetic components-root and
  // decomposition-graph synthetic entries don't have a selectable
  // state either (clicking navigates to the view). Actual leaf
  // selection is handled by onSelect.
  const isPureHeader = item.id === SYNTHETIC_IDS.COMPONENTS_ROOT;

  const paddingLeft = 8 + depth * 12;

  // Status dots: pending draft (amber) + generation running (pulsing amber).
  // Descendant flags show a dimmer indicator when the row is
  // collapsed so the user knows there's activity deeper in the
  // tree without expanding.
  const showPendingSelf = item.status.has_pending_draft;
  const showRunningSelf = item.status.generation_running;
  const showErrorSelf = item.status.has_error;
  const showBlueSelf = item.status.needs_user_action;
  const showGreenSelf =
    item.node !== null &&
    item.node.has_content &&
    !showRunningSelf &&
    !showErrorSelf &&
    !showPendingSelf &&
    !showBlueSelf;
  // Phase 9 — stale renders orthogonally to the other flags. An
  // approved-but-stale node shows green + fuchsia; a stale draft
  // shows amber + fuchsia. The distinction is "this node's own
  // generation state" (running/pending/error/approved) vs. "an
  // upstream changed since the last regen" (stale).
  const showStaleSelf = item.status.is_stale;
  const showPendingDescendant =
    !isExpanded && item.status.descendant_has_pending_draft && !showPendingSelf;
  const showRunningDescendant =
    !isExpanded && item.status.descendant_generation_running && !showRunningSelf;
  const showErrorDescendant =
    !isExpanded && item.status.descendant_has_error && !showErrorSelf;
  const showBlueDescendant =
    !isExpanded && item.status.descendant_needs_user_action && !showBlueSelf;
  const showStaleDescendant =
    !isExpanded && item.status.descendant_is_stale && !showStaleSelf;

  return (
    <li role="treeitem" aria-expanded={hasChildren ? isExpanded : undefined}>
      <div
        className={`group flex items-center gap-1 pr-2 py-1 rounded cursor-pointer ${
          isSelected
            ? 'bg-purple-900/40 text-white'
            : 'text-gray-300 hover:bg-gray-800/60 hover:text-white'
        }`}
        style={{ paddingLeft }}
        onClick={() => {
          if (isPureHeader) {
            // Pure headers only toggle on click, never select.
            if (hasChildren) onToggle(item.id);
            return;
          }
          onSelect(item);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            if (isPureHeader) {
              if (hasChildren) onToggle(item.id);
            } else {
              onSelect(item);
            }
          } else if (e.key === 'ArrowRight' && hasChildren && !isExpanded) {
            e.preventDefault();
            onToggle(item.id);
          } else if (e.key === 'ArrowLeft' && hasChildren && isExpanded) {
            e.preventDefault();
            onToggle(item.id);
          }
        }}
        tabIndex={0}
      >
        {hasChildren ? (
          <button
            type="button"
            aria-label={isExpanded ? 'Collapse' : 'Expand'}
            onClick={(e) => {
              e.stopPropagation();
              onToggle(item.id);
            }}
            className="shrink-0 w-4 h-4 flex items-center justify-center text-gray-500 hover:text-gray-300"
          >
            <span
              className={`inline-block transition-transform ${isExpanded ? 'rotate-90' : ''}`}
            >
              ▶
            </span>
          </button>
        ) : (
          <span className="shrink-0 w-4" aria-hidden />
        )}
        <RoleIcon role={item.role} kind={item.node?.kind ?? null} />
        <span className="flex-1 min-w-0 truncate">{item.label}</span>
        <StatusBadges
          running={showRunningSelf}
          pending={showPendingSelf}
          errored={showErrorSelf}
          needsUserAction={showBlueSelf}
          approved={showGreenSelf}
          stale={showStaleSelf}
          descendantRunning={showRunningDescendant}
          descendantPending={showPendingDescendant}
          descendantErrored={showErrorDescendant}
          descendantNeedsUserAction={showBlueDescendant}
          descendantStale={showStaleDescendant}
        />
      </div>
      {hasChildren && isExpanded && (
        <ul role="group" className="space-y-0.5">
          {item.children.map((child) => (
            <NavTreeRow
              key={child.id}
              item={child}
              depth={depth + 1}
              selectedId={selectedId}
              expanded={expanded}
              onToggle={onToggle}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

function RoleIcon({
  role,
  kind,
}: {
  role: NavItem['role'];
  kind: string | null;
}) {
  // Single-char glyphs keep the tree tight on mobile. Colour
  // dispatches on kind for comps so domain / presentational
  // read differently at a glance.
  const domainColour = kind === 'presentational' ? 'text-purple-300' : 'text-blue-300';

  switch (role) {
    case 'expansion':
      return <span className="shrink-0 w-4 text-center text-gray-400">§</span>;
    case 'reqs':
      return <span className="shrink-0 w-4 text-center text-gray-400">§</span>;
    case 'sysarch':
      return <span className="shrink-0 w-4 text-center text-gray-400">§</span>;
    case 'vocabulary':
      return <span className="shrink-0 w-4 text-center text-amber-300">A</span>;
    case 'references':
      return <span className="shrink-0 w-4 text-center text-amber-300">¶</span>;
    case 'dag':
      return <span className="shrink-0 w-4 text-center text-cyan-300">◇</span>;
    case 'components-root':
      return <span className="shrink-0 w-4 text-center text-gray-500">⋯</span>;
    case 'component-top':
      return <span className={`shrink-0 w-4 text-center ${domainColour}`}>■</span>;
    case 'component-sub':
      return <span className={`shrink-0 w-4 text-center ${domainColour}`}>▪</span>;
    case 'component-subreqs':
      return <span className="shrink-0 w-4 text-center text-green-400">§</span>;
    case 'component-fanin':
      return <span className="shrink-0 w-4 text-center text-purple-300">⬢</span>;
    case 'component-impl':
    case 'subcomponent-impl':
      return <span className="shrink-0 w-4 text-center text-yellow-300">⟨⟩</span>;
  }
}

function StatusBadges({
  running,
  pending,
  errored,
  needsUserAction,
  approved,
  stale,
  descendantRunning,
  descendantPending,
  descendantErrored,
  descendantNeedsUserAction,
  descendantStale,
}: {
  running: boolean;
  pending: boolean;
  errored: boolean;
  needsUserAction: boolean;
  approved: boolean;
  stale: boolean;
  descendantRunning: boolean;
  descendantPending: boolean;
  descendantErrored: boolean;
  descendantNeedsUserAction: boolean;
  descendantStale: boolean;
}) {
  if (
    !running &&
    !pending &&
    !errored &&
    !needsUserAction &&
    !approved &&
    !stale &&
    !descendantRunning &&
    !descendantPending &&
    !descendantErrored &&
    !descendantNeedsUserAction &&
    !descendantStale
  )
    return null;
  return (
    <span className="shrink-0 flex items-center gap-1 pl-2">
      {running && (
        <span
          title="Generating"
          aria-label="Generating"
          className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"
        />
      )}
      {errored && !running && (
        <span
          title="Generation failed"
          aria-label="Generation failed"
          className="inline-block w-1.5 h-1.5 rounded-full bg-red-500"
        />
      )}
      {pending && !running && !errored && (
        <span
          title="Draft awaiting review"
          aria-label="Draft awaiting review"
          className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400"
        />
      )}
      {needsUserAction && !running && !errored && !pending && (
        <span
          title="Ready — waiting on your kick"
          aria-label="Ready — waiting on your kick"
          className="inline-block w-1.5 h-1.5 rounded-full bg-sky-400"
        />
      )}
      {approved && (
        <span
          title="Approved"
          aria-label="Approved"
          className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500"
        />
      )}
      {stale && (
        <span
          title="Stale — upstream changed"
          aria-label="Stale — upstream changed"
          className="inline-block w-1.5 h-1.5 rounded-full bg-fuchsia-400"
        />
      )}
      {descendantRunning && !running && (
        <span
          title="Descendant generating"
          aria-label="Descendant generating"
          className="inline-block w-1 h-1 rounded-full bg-amber-400/50 animate-pulse"
        />
      )}
      {descendantErrored && !errored && !descendantRunning && (
        <span
          title="Descendant generation failed"
          aria-label="Descendant generation failed"
          className="inline-block w-1 h-1 rounded-full bg-red-500/60"
        />
      )}
      {descendantNeedsUserAction &&
        !needsUserAction &&
        !descendantRunning &&
        !descendantErrored && (
          <span
            title="Descendant ready — waiting on your kick"
            aria-label="Descendant ready — waiting on your kick"
            className="inline-block w-1 h-1 rounded-full bg-sky-400/60"
          />
        )}
      {descendantPending &&
        !pending &&
        !descendantRunning &&
        !descendantErrored &&
        !descendantNeedsUserAction && (
          <span
            title="Descendant has draft awaiting review"
            aria-label="Descendant has draft awaiting review"
            className="inline-block w-1 h-1 rounded-full bg-amber-400/50"
          />
        )}
      {descendantStale && !stale && (
        <span
          title="Descendant stale — upstream changed"
          aria-label="Descendant stale — upstream changed"
          className="inline-block w-1 h-1 rounded-full bg-fuchsia-400/60"
        />
      )}
    </span>
  );
}
