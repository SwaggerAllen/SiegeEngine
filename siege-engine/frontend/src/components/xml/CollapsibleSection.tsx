import type { ReactNode } from 'react';

interface Props {
  /** Summary shown collapsed; clickable to expand. */
  summary: ReactNode;
  /** Optional right-side metadata (badges, counts, IDs). */
  meta?: ReactNode;
  /** Start expanded. Defaults to false — birds-eye first. */
  defaultOpen?: boolean;
  /** Extra className on the outer <details>. */
  className?: string;
  children: ReactNode;
}

/**
 * Shared collapsible section used by every tier's XML renderer
 * to give a birds-eye view of the doc. Uses HTML ``<details>``
 * so collapse/expand is keyboard-navigable, ARIA-correct, and
 * needs no state plumbing.
 *
 * The summary row shows the left-side primary handle (name /
 * title / section label) plus optional right-side metadata
 * (kind, alias, id, counts). A chevron rotates to indicate
 * open state.
 */
export function CollapsibleSection({
  summary,
  meta,
  defaultOpen = false,
  className,
  children,
}: Props) {
  return (
    <details
      className={`group border border-gray-700 rounded bg-gray-800/40 ${className ?? ''}`}
      {...(defaultOpen ? { open: true } : {})}
    >
      <summary className="flex items-center gap-2 cursor-pointer px-3 py-2 hover:bg-gray-800 select-none list-none [&::-webkit-details-marker]:hidden">
        <span className="text-gray-500 text-xs w-3 transition-transform group-open:rotate-90">
          ▶
        </span>
        <span className="flex-1 min-w-0 text-sm font-semibold text-white truncate">
          {summary}
        </span>
        {meta && (
          <span className="shrink-0 text-xs text-gray-400 flex items-center gap-2">
            {meta}
          </span>
        )}
      </summary>
      <div className="px-4 py-3 border-t border-gray-700 space-y-3">
        {children}
      </div>
    </details>
  );
}
