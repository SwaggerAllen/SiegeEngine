import type { ReactNode } from 'react';

interface BottomPaneProps {
  handle: ReactNode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}

/**
 * Collapsible bottom sheet used in DocumentsTab and PipelineTab.
 * The `handle` is always visible; `children` appear when `open` is true.
 */
export function BottomPane({ handle, open, onOpenChange, children }: BottomPaneProps) {
  return (
    <div className="shrink-0 border-t border-gray-700 bg-gray-900">
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer select-none min-h-[57px]"
        onClick={() => onOpenChange(!open)}
      >
        {handle}
        <svg
          className={`w-4 h-4 text-gray-400 shrink-0 transition-transform duration-150 ${open ? '' : 'rotate-180'}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
        </svg>
      </div>
      {open && (
        <div className="border-t border-gray-700/50 overflow-y-auto" style={{ maxHeight: '45vh' }}>
          {children}
        </div>
      )}
    </div>
  );
}

// Status badge used in pane handles
const STATUS_COLORS: Record<string, string> = {
  approved: 'bg-green-900/60 text-green-300',
  awaiting_review: 'bg-yellow-900/60 text-yellow-300',
  generating: 'bg-blue-900/60 text-blue-300',
  ai_reviewing: 'bg-purple-900/60 text-purple-300',
  stale: 'bg-orange-900/60 text-orange-300',
  rejected: 'bg-red-900/60 text-red-300',
  failed: 'bg-red-900/60 text-red-300',
  pending: 'bg-gray-700 text-gray-400',
};

const STATUS_LABELS: Record<string, string> = {
  approved: 'Approved',
  awaiting_review: 'Awaiting Review',
  generating: 'Generating',
  ai_reviewing: 'AI Reviewing',
  stale: 'Stale',
  rejected: 'Rejected',
  failed: 'Failed',
  pending: 'Pending',
};

export function ArtifactStatusBadge({ status }: { status: string }) {
  const color = STATUS_COLORS[status] ?? 'bg-gray-700 text-gray-400';
  const label = STATUS_LABELS[status] ?? status;
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded shrink-0 ${color}`}>{label}</span>
  );
}
