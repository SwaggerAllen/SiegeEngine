import { useState, type ReactNode } from 'react';

interface Props {
  /** Content for the "Document" subtab — typically a BootstrapDraftPanel. */
  document: ReactNode;
  /** Content for the "Nodes" subtab — typically the minted-node list(s). */
  nodes: ReactNode;
  /**
   * Stable id used in the ``role="tabpanel"`` + ``aria-labelledby`` plumbing
   * so screen readers can distinguish the subtabs across the three parent
   * dashboard tabs. Typical values: ``expansion``, ``requirements``,
   * ``architecture``.
   */
  idPrefix: string;
  /**
   * Optional label override for the "Nodes" subtab. The document label is
   * always "Document" because the parent tab name already tells the user
   * which bootstrap doc they're looking at. The nodes label defaults to
   * "Nodes" but individual parents may want something more specific like
   * "Components & policies".
   */
  nodesLabel?: string;
}

/**
 * Switchable subtabs used inside each bootstrap dashboard tab
 * (Expansion / Requirements / Architecture). The parent tab body
 * used to stack the LLM-authored document panel on top of the
 * minted-node list, which forced the user to scroll to the bottom
 * to see what actually hit the DAG. This component splits the two
 * into sibling subtabs that the user can flip between without
 * scrolling.
 *
 * Default active subtab is "Document" — that's the review surface
 * the user is most likely to be looking at mid-flow. Switching
 * away from the parent tab resets the subtab state (it lives in
 * local ``useState``), which is fine for MVP; elevating to parent
 * state is straightforward if users want the selection to persist.
 */
export function BootstrapSubtabs({
  document,
  nodes,
  idPrefix,
  nodesLabel = 'Nodes',
}: Props) {
  const [active, setActive] = useState<'document' | 'nodes'>('document');
  const baseClasses = 'px-3 py-1.5 text-xs border-b-2 -mb-px transition-colors';
  const activeClasses = 'border-blue-500 text-white';
  const idleClasses =
    'border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-600 cursor-pointer';

  return (
    <div className="h-full flex flex-col">
      <nav
        className="border-b border-gray-800 px-3 flex items-center gap-1 shrink-0"
        role="tablist"
        aria-label={`${idPrefix} subtabs`}
      >
        <button
          type="button"
          role="tab"
          aria-selected={active === 'document'}
          aria-controls={`subtabpanel-${idPrefix}-document`}
          onClick={() => setActive('document')}
          className={
            active === 'document'
              ? `${baseClasses} ${activeClasses}`
              : `${baseClasses} ${idleClasses}`
          }
        >
          Document
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={active === 'nodes'}
          aria-controls={`subtabpanel-${idPrefix}-nodes`}
          onClick={() => setActive('nodes')}
          className={
            active === 'nodes'
              ? `${baseClasses} ${activeClasses}`
              : `${baseClasses} ${idleClasses}`
          }
        >
          {nodesLabel}
        </button>
      </nav>
      <div className="flex-1 overflow-auto">
        {active === 'document' && (
          <div
            role="tabpanel"
            id={`subtabpanel-${idPrefix}-document`}
            className="h-full"
          >
            {document}
          </div>
        )}
        {active === 'nodes' && (
          <div
            role="tabpanel"
            id={`subtabpanel-${idPrefix}-nodes`}
            className="h-full"
          >
            {nodes}
          </div>
        )}
      </div>
    </div>
  );
}
