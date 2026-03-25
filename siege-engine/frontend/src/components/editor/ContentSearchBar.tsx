import { useState, useEffect, useCallback, useRef } from 'react';
import type { RefObject } from 'react';

// ---------------------------------------------------------------------------
// Highlight helpers — walk text nodes, wrap matches in <mark> elements
// ---------------------------------------------------------------------------

function clearMarks(container: HTMLElement) {
  const marks = container.querySelectorAll('mark[data-search-highlight]');
  marks.forEach((mark) => {
    const parent = mark.parentNode;
    if (parent) {
      parent.replaceChild(document.createTextNode(mark.textContent || ''), mark);
      parent.normalize(); // merge adjacent text nodes
    }
  });
}

function highlightAll(container: HTMLElement, query: string): HTMLElement[] {
  const marks: HTMLElement[] = [];
  if (!query) return marks;

  const lowerQuery = query.toLowerCase();
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const textNodes: Text[] = [];
  let node: Node | null;
  while ((node = walker.nextNode())) {
    textNodes.push(node as Text);
  }

  for (const textNode of textNodes) {
    const text = textNode.textContent || '';
    const lowerText = text.toLowerCase();
    let idx = lowerText.indexOf(lowerQuery);
    if (idx === -1) continue;

    // Split this text node at each match
    const frag = document.createDocumentFragment();
    let lastEnd = 0;
    while (idx !== -1) {
      // Text before match
      if (idx > lastEnd) {
        frag.appendChild(document.createTextNode(text.slice(lastEnd, idx)));
      }
      // The match itself
      const mark = document.createElement('mark');
      mark.setAttribute('data-search-highlight', '');
      mark.className = 'bg-yellow-500/40 text-inherit rounded-sm';
      mark.textContent = text.slice(idx, idx + query.length);
      frag.appendChild(mark);
      marks.push(mark);
      lastEnd = idx + query.length;
      idx = lowerText.indexOf(lowerQuery, lastEnd);
    }
    // Remaining text
    if (lastEnd < text.length) {
      frag.appendChild(document.createTextNode(text.slice(lastEnd)));
    }
    textNode.parentNode!.replaceChild(frag, textNode);
  }

  return marks;
}

const ACTIVE_CLASS = '!bg-orange-500/60';

function setActiveMark(marks: HTMLElement[], index: number) {
  marks.forEach((m) => m.classList.remove(ACTIVE_CLASS));
  if (marks[index]) {
    marks[index].classList.add(ACTIVE_CLASS);
    marks[index].scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

// ---------------------------------------------------------------------------
// ContentSearchBar
// ---------------------------------------------------------------------------

interface ContentSearchBarProps {
  /** Ref to the scrollable container whose text should be searched */
  containerRef: RefObject<HTMLElement | null>;
  /** Optional: re-run highlights when content changes (e.g. artifact.id) */
  contentKey?: string;
}

export function ContentSearchBar({ containerRef, contentKey }: ContentSearchBarProps) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [currentIdx, setCurrentIdx] = useState(0);
  const marksRef = useRef<HTMLElement[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // Apply highlights whenever query or content changes
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    clearMarks(container);
    if (!query.trim()) {
      marksRef.current = [];
      setCurrentIdx(0);
      return;
    }
    const marks = highlightAll(container, query);
    marksRef.current = marks;
    setCurrentIdx(0);
    if (marks.length > 0) setActiveMark(marks, 0);
  }, [query, contentKey, containerRef]);

  // Clean up marks on unmount or close
  useEffect(() => {
    return () => {
      const container = containerRef.current;
      if (container) clearMarks(container);
    };
  }, [containerRef]);

  // Keyboard shortcut: Ctrl/Cmd+F to open
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
        // Only intercept if this container is visible
        const container = containerRef.current;
        if (!container || container.offsetParent === null) return;
        e.preventDefault();
        setOpen(true);
        setTimeout(() => inputRef.current?.focus(), 0);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [containerRef]);

  const goTo = useCallback(
    (idx: number) => {
      const marks = marksRef.current;
      if (marks.length === 0) return;
      const next = ((idx % marks.length) + marks.length) % marks.length;
      setCurrentIdx(next);
      setActiveMark(marks, next);
    },
    [],
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (e.shiftKey) {
        goTo(currentIdx - 1);
      } else {
        goTo(currentIdx + 1);
      }
    } else if (e.key === 'Escape') {
      handleClose();
    }
  };

  const handleClose = () => {
    setOpen(false);
    setQuery('');
    const container = containerRef.current;
    if (container) clearMarks(container);
    marksRef.current = [];
  };

  if (!open) return null;

  const matchCount = marksRef.current.length;

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-800 border-b border-gray-700">
      <div className="relative flex-1 max-w-sm">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Find in document..."
          autoFocus
          className="w-full px-3 py-1 bg-gray-700 text-white text-xs rounded border border-gray-600 focus:border-blue-500 focus:outline-none placeholder-gray-500 pr-16"
        />
        {query && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400">
            {matchCount > 0 ? `${currentIdx + 1}/${matchCount}` : 'No results'}
          </span>
        )}
      </div>
      <button
        onClick={() => goTo(currentIdx - 1)}
        disabled={matchCount === 0}
        className="px-1.5 py-1 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded disabled:opacity-30"
        title="Previous match (Shift+Enter)"
      >
        ▲
      </button>
      <button
        onClick={() => goTo(currentIdx + 1)}
        disabled={matchCount === 0}
        className="px-1.5 py-1 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded disabled:opacity-30"
        title="Next match (Enter)"
      >
        ▼
      </button>
      <button
        onClick={handleClose}
        className="px-1.5 py-1 text-gray-400 hover:text-white text-xs"
        title="Close (Escape)"
      >
        ✕
      </button>
    </div>
  );
}
