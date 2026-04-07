interface ActionButtonsBarProps {
  canPrune: boolean;
  canReparse: boolean;
  canPruneDescendants: boolean;
  pruning: boolean;
  reparsing: boolean;
  pruningDescendants: boolean;
  reparseResult: string | null;
  onPrune: () => void;
  onReparse: () => void;
  onPruneDescendants: () => void;
  pruneLabel?: string;
}

export function ActionButtonsBar({
  canPrune,
  canReparse,
  canPruneDescendants,
  pruning,
  reparsing,
  pruningDescendants,
  reparseResult,
  onPrune,
  onReparse,
  onPruneDescendants,
  pruneLabel = '🗑 Prune',
}: ActionButtonsBarProps) {
  if (!canPrune && !canReparse && !canPruneDescendants) return null;
  return (
    <>
      {canPrune && (
        <button
          onClick={onPrune}
          disabled={pruning}
          className="px-3 py-1.5 bg-gray-700 hover:bg-red-700 text-gray-300 hover:text-white text-xs rounded disabled:opacity-50 transition-colors min-h-[44px] md:min-h-0"
        >
          {pruning ? 'Pruning...' : pruneLabel}
        </button>
      )}
      {canPruneDescendants && (
        <button
          onClick={onPruneDescendants}
          disabled={pruningDescendants}
          className="px-3 py-1.5 bg-orange-700 hover:bg-orange-600 text-white text-xs rounded disabled:opacity-50 transition-colors min-h-[44px] md:min-h-0"
        >
          {pruningDescendants ? 'Pruning...' : 'Prune Descendants'}
        </button>
      )}
      {canReparse && (
        <button
          onClick={onReparse}
          disabled={reparsing}
          className="px-3 py-1.5 bg-indigo-700 hover:bg-indigo-600 text-white text-xs rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
        >
          {reparsing ? 'Reparsing...' : 'Reparse Children'}
        </button>
      )}
      {reparseResult && (
        <span
          className={`text-xs ${
            reparseResult === 'No changes detected'
              ? 'text-gray-400'
              : reparseResult === 'Reparse failed'
                ? 'text-red-400'
                : 'text-green-400'
          }`}
        >
          {reparseResult}
        </span>
      )}
    </>
  );
}
