import type { AvailableGroup, TierGroupKey } from './tierFilter';

interface Props {
  available: AvailableGroup[];
  hidden: ReadonlySet<TierGroupKey>;
  onToggle: (key: TierGroupKey) => void;
}

/**
 * Chip row for filtering tier groups out of a DAG view. Each chip
 * shows a tier-group label and is either "on" (visible, default)
 * or "off" (hidden, struck-through). Tap to toggle.
 *
 * Wrappers compute ``available`` from the current element list so
 * groups with no nodes don't render a chip — toggling nothing is
 * confusing. State lives in the URL ``?hide=`` param the wrapper
 * owns.
 */
export function TierFilterChips({ available, hidden, onToggle }: Props) {
  if (available.length === 0) return null;
  return (
    <div
      className="flex flex-wrap items-center gap-1 text-[11px]"
      data-testid="tier-filter-chips"
    >
      <span className="text-gray-500 mr-1">Show:</span>
      {available.map(({ key, label }) => {
        const isHidden = hidden.has(key);
        return (
          <button
            key={key}
            type="button"
            onClick={() => onToggle(key)}
            aria-pressed={!isHidden}
            data-testid={`tier-filter-chip-${key}`}
            className={[
              'px-2 py-0.5 rounded border transition-colors',
              isHidden
                ? 'border-gray-700 text-gray-500 line-through bg-gray-900/40 hover:bg-gray-800'
                : 'border-gray-600 text-gray-200 bg-gray-800 hover:bg-gray-700',
            ].join(' ')}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
