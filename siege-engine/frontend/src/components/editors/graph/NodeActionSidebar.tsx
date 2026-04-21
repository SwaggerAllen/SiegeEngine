import type { ReactNode } from 'react';
import { useIsNarrowViewport } from '../../../hooks/useMatchMedia';

/**
 * Right-drawer (desktop) / bottom-sheet (mobile) sidebar for the
 * editable graph surfaces.
 *
 * Shown when the user has tapped a node, an edge, or staged a
 * new edge. The caller passes in:
 *
 * - `title` — a short label naming what's selected (e.g.
 *   "Billing" or "Billing → Payments").
 * - `actions` — React children rendering the per-state action
 *   buttons. The caller owns the full action catalogue and
 *   which ones make sense for the current selection.
 * - `onCancel` — invoked by the sidebar's "Close" button and
 *   on ESC.
 *
 * Layout switch is gated by a ``(max-width: 768px)`` media
 * query (see ``useIsNarrowViewport``). On narrow viewports the
 * sidebar renders as a fixed bottom sheet with ``max-height:
 * 60vh`` and independent scroll so the graph canvas stays
 * usable above.
 */
export interface NodeActionSidebarProps {
  title: string;
  subtitle?: string;
  actions: ReactNode;
  onCancel?: () => void;
}

export function NodeActionSidebar({
  title,
  subtitle,
  actions,
  onCancel,
}: NodeActionSidebarProps) {
  const narrow = useIsNarrowViewport();
  const containerClass = narrow
    ? 'fixed inset-x-0 bottom-0 z-40 max-h-[60vh] border-t border-gray-800 bg-gray-950 flex flex-col shadow-xl'
    : 'w-72 shrink-0 border-l border-gray-800 bg-gray-950 flex flex-col';
  return (
    <aside
      className={containerClass}
      data-testid="node-action-sidebar"
      data-layout={narrow ? 'bottom-sheet' : 'side-drawer'}
    >
      <header className="px-3 py-2 border-b border-gray-800 flex items-baseline justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-gray-100 truncate">
            {title}
          </div>
          {subtitle && (
            <div className="text-xs text-gray-500 truncate">{subtitle}</div>
          )}
        </div>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="text-xs text-gray-500 hover:text-gray-200 px-1"
            aria-label="Close node actions"
          >
            Close
          </button>
        )}
      </header>
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
        {actions}
      </div>
    </aside>
  );
}

/**
 * Shared button styling for sidebar actions. Editors use these
 * to stay visually consistent across the three graph editors.
 */
export function SidebarActionButton({
  label,
  onClick,
  disabled,
  variant = 'default',
  title,
  testId,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  variant?: 'default' | 'primary' | 'destructive';
  title?: string;
  testId?: string;
}) {
  const palette =
    variant === 'primary'
      ? 'bg-blue-700 hover:bg-blue-600 text-white'
      : variant === 'destructive'
        ? 'bg-red-900 hover:bg-red-800 text-white'
        : 'bg-gray-800 hover:bg-gray-700 text-gray-200';
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`w-full text-left px-3 py-1.5 text-xs rounded disabled:opacity-40 ${palette}`}
      title={title}
      data-testid={testId}
    >
      {label}
    </button>
  );
}
