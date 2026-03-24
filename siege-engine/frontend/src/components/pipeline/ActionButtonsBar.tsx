interface ActionButtonsBarProps {
  canPrune: boolean;
  canReparse: boolean;
  pruning: boolean;
  reparsing: boolean;
  reparseResult: string | null;
  onPrune: () => void;
  onReparse: () => void;
}

export function ActionButtonsBar({
  canPrune,
  canReparse,
  pruning,
  reparsing,
  reparseResult,
  onPrune,
  onReparse,
}: ActionButtonsBarProps) {
  if (!canPrune && !canReparse) return null;
  return (
    <>
      {canPrune && (
        <button
          onClick={onPrune}
          disabled={pruning}
          className="px-3 py-1.5 bg-gray-700 hover:bg-red-700 text-gray-300 hover:text-white text-xs rounded disabled:opacity-50 transition-colors min-h-[44px] md:min-h-0"
        >
          {pruning ? 'Pruning...' : '🗑 Prune'}
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
            reparseResult.startsWith('Restored')
              ? 'text-green-400'
              : reparseResult === 'No missing entities found'
                ? 'text-gray-400'
                : 'text-red-400'
          }`}
        >
          {reparseResult}
        </span>
      )}
    </>
  );
}
