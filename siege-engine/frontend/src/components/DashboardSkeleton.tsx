/** Pulsing skeleton shown while project data loads. */
export function DashboardSkeleton() {
  return (
    <div className="flex-1 flex flex-col overflow-hidden animate-pulse">
      {/* Fake header */}
      <div className="border-b border-gray-700 px-4 py-3 flex items-center gap-4">
        <div className="h-4 w-20 bg-gray-700 rounded" />
        <div className="h-5 w-40 bg-gray-700 rounded" />
      </div>
      {/* Fake nav */}
      <div className="border-b border-gray-700 px-4 py-2">
        <div className="h-4 w-24 bg-gray-700 rounded" />
      </div>
      {/* Fake two-pane content */}
      <div className="flex-1 flex">
        <div className="w-3/5 border-r border-gray-700 p-6">
          <div className="h-4 w-48 bg-gray-700 rounded mb-4" />
          <div className="h-64 bg-gray-800 rounded" />
        </div>
        <div className="w-2/5 p-6">
          <div className="h-4 w-32 bg-gray-700 rounded mb-4" />
          <div className="h-32 bg-gray-800 rounded" />
        </div>
      </div>
    </div>
  );
}

/** Smaller skeleton for lazy-loaded tab content */
export function TabSkeleton() {
  return (
    <div className="flex-1 flex items-center justify-center animate-pulse">
      <div className="h-6 w-32 bg-gray-700 rounded" />
    </div>
  );
}
