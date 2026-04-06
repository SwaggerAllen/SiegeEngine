import { useEffect, useState } from 'react';
import { getComponents, type ComponentInfo } from '../../api/pipeline';

const CHANGE_BADGES: Record<string, { label: string; className: string }> = {
  new: { label: 'New', className: 'bg-green-900/50 text-green-300 border-green-600/40' },
  existing: { label: 'Existing', className: 'bg-gray-700/50 text-gray-300 border-gray-500/40' },
  removed: { label: 'Removed', className: 'bg-red-900/50 text-red-300 border-red-600/40' },
};

export function ComponentDependencyList({ projectId, refreshKey, parentKey }: { projectId: string; refreshKey?: number; parentKey?: string | null }) {
  const [components, setComponents] = useState<ComponentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getComponents(projectId, parentKey)
      .then((data) => {
        if (!cancelled) setComponents(data);
      })
      .catch(console.error)
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [projectId, refreshKey, parentKey]);

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // Build a lookup for resolving keys to names
  const keyToName = new Map(components.map((c) => [c.key, c.name]));
  const hasAnyChanges = components.some((c) => c.change);

  if (loading) {
    return <div className="p-4 text-sm text-gray-400">Loading components...</div>;
  }

  if (components.length === 0) {
    return <div className="p-4 text-sm text-gray-400">No components extracted yet.</div>;
  }

  return (
    <div className="flex-1 overflow-auto p-3 pb-64 space-y-1">
      {hasAnyChanges && (
        <div className="flex items-center gap-2 px-1 pb-2 text-xs text-gray-500">
          <span>Showing changes vs. previous extraction</span>
        </div>
      )}
      {components.map((comp) => {
        const isOpen = expanded.has(comp.key);
        const hasDeps = comp.dependencies.length > 0;
        const hasDepnts = comp.dependents.length > 0;
        const hasDetails = hasDeps || hasDepnts || comp.description;
        const badge = comp.change ? CHANGE_BADGES[comp.change] : null;
        const isRemoved = comp.change === 'removed';

        return (
          <div
            key={comp.key}
            className={`border rounded ${
              isRemoved
                ? 'border-red-800/50 opacity-60'
                : comp.change === 'new'
                ? 'border-green-700/50'
                : 'border-gray-700'
            }`}
          >
            <button
              onClick={() => hasDetails && toggle(comp.key)}
              className={`w-full flex items-center gap-2 px-3 py-2 text-left text-sm ${
                hasDetails ? 'cursor-pointer hover:bg-gray-800/50' : 'cursor-default'
              }`}
            >
              {hasDetails && (
                <svg
                  className={`w-3 h-3 text-gray-500 shrink-0 transition-transform ${isOpen ? 'rotate-90' : ''}`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              )}
              {!hasDetails && <span className="w-3 shrink-0" />}
              <span className={`font-medium truncate ${isRemoved ? 'line-through text-gray-400' : 'text-white'}`}>
                {comp.name}
              </span>
              <span className="text-xs text-gray-500 shrink-0">{comp.key}</span>
              {badge && (
                <span className={`text-xs px-1.5 py-0.5 rounded border shrink-0 ${badge.className}`}>
                  {badge.label}
                </span>
              )}
              {hasDeps && (
                <span className="ml-auto text-xs text-gray-500 shrink-0">
                  {comp.dependencies.length} dep{comp.dependencies.length !== 1 ? 's' : ''}
                </span>
              )}
            </button>

            {isOpen && (
              <div className="px-3 pb-3 pt-1 space-y-2 border-t border-gray-700/50">
                {comp.description && (
                  <p className="text-xs text-gray-400">{comp.description}</p>
                )}

                {hasDeps && (
                  <div>
                    <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                      Depends on
                    </span>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {comp.dependencies.map((depKey) => (
                        <span
                          key={depKey}
                          className="text-xs px-2 py-0.5 rounded bg-blue-900/40 text-blue-300 border border-blue-700/40"
                        >
                          {keyToName.get(depKey) || depKey}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {hasDepnts && (
                  <div>
                    <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                      Required by
                    </span>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {comp.dependents.map((depKey) => (
                        <span
                          key={depKey}
                          className="text-xs px-2 py-0.5 rounded bg-green-900/40 text-green-300 border border-green-700/40"
                        >
                          {keyToName.get(depKey) || depKey}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
