import type { Tab, TabScope } from './tabScope';

interface Props {
  scope: TabScope;
  onSelectTab: (tab: Tab) => void;
}

/**
 * Horizontal tab strip for the detail pane's contextual scope.
 * Hidden when there are no tabs (no selection, synthetic view,
 * or an unrecognised tier). The scope label above the tabs gives
 * the user a persistent indicator of what they're viewing — e.g.
 * "Billing" while clicking through that comp's Overview / Comparch
 * tabs.
 */
export function TabStrip({ scope, onSelectTab }: Props) {
  if (scope.tabs.length === 0) return null;
  return (
    <div className="border-b border-gray-700 bg-gray-900">
      {scope.scopeLabel && (
        <div className="px-4 pt-2 text-xs text-gray-400 truncate" data-testid="tab-scope-label">
          {scope.scopeLabel}
        </div>
      )}
      <nav role="tablist" aria-label="Detail view" className="px-2 flex gap-0.5 overflow-x-auto">
        {scope.tabs.map((tab) => {
          const isActive = tab.key === scope.activeKey;
          return (
            <button
              key={tab.key}
              role="tab"
              type="button"
              aria-selected={isActive}
              onClick={() => onSelectTab(tab)}
              className={
                'px-3 py-1.5 text-xs whitespace-nowrap border-b-2 transition-colors ' +
                (isActive
                  ? 'border-blue-400 text-white font-semibold'
                  : 'border-transparent text-gray-400 hover:text-gray-200')
              }
            >
              {tab.label}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
