import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

interface Props {
  projectId: string;
}

/**
 * Hamburger menu for the project dashboard header.
 *
 * A small dropdown of project-scoped actions. Today it only houses
 * the settings link; more items will land as other project-level
 * routes ship. Clicking outside or pressing Escape closes it.
 */
export function DashboardMenu({ projectId }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onClickOutside = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onClickOutside);
    document.addEventListener('keydown', onEscape);
    return () => {
      document.removeEventListener('mousedown', onClickOutside);
      document.removeEventListener('keydown', onEscape);
    };
  }, [open]);

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        aria-label="Project menu"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((v) => !v)}
        className="p-1.5 rounded hover:bg-gray-700 text-gray-300 hover:text-white"
      >
        {/* Three-bar hamburger icon, inline SVG so no asset pipeline. */}
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-1 w-48 bg-gray-800 border border-gray-700 rounded shadow-lg z-20 py-1 text-sm"
        >
          <Link
            to={`/projects/${projectId}/decomposition`}
            role="menuitem"
            onClick={() => setOpen(false)}
            className="block px-3 py-2 hover:bg-gray-700 text-gray-200"
          >
            Decomposition Graph
          </Link>
          <Link
            to={`/projects/${projectId}/settings`}
            role="menuitem"
            onClick={() => setOpen(false)}
            className="block px-3 py-2 hover:bg-gray-700 text-gray-200"
          >
            Settings
          </Link>
        </div>
      )}
    </div>
  );
}
