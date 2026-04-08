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
  /** Optional: raw text content for the copy-to-clipboard button */
  copyContent?: string | null;
}

export function ContentSearchBar({ containerRef, contentKey, copyContent }: ContentSearchBarProps) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
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
    const container = containerRef.current;
    return () => {
      if (container) clearMarks(container);
    };
  }, [containerRef]);

  const handleOpen = useCallback(() => {
    setOpen(true);
    setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  // Keyboard shortcut: Ctrl/Cmd+F to open
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
        // Only intercept if this container is visible
        const container = containerRef.current;
        if (!container || container.offsetParent === null) return;
        e.preventDefault();
        handleOpen();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [containerRef, handleOpen]);

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

  const handleCopy = useCallback(async () => {
    if (!copyContent) return;
    try {
      await navigator.clipboard.writeText(copyContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for non-HTTPS contexts
      const ta = document.createElement('textarea');
      ta.value = copyContent;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [copyContent]);

  if (!open) {
    const wordCount = copyContent ? copyContent.trim().split(/\s+/).filter(Boolean).length : 0;
    const charCount = copyContent ? copyContent.length : 0;

    return (
      <div className="flex justify-between items-center px-3 py-1 border-b border-gray-700">
        {copyContent ? (
          <span className="text-xs text-gray-500 font-mono">
            {wordCount.toLocaleString()} words &middot; {charCount.toLocaleString()} chars
          </span>
        ) : <span />}
        <div className="flex">
        {copyContent && (
          <button
            onClick={handleCopy}
            className="p-2 min-h-[44px] min-w-[44px] flex items-center justify-center text-gray-400 hover:text-white hover:bg-gray-700 rounded"
            title={copied ? 'Copied!' : 'Copy document to clipboard'}
          >
            {copied ? (
              <svg className="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            )}
          </button>
        )}
        <button
          onClick={handleOpen}
          className="p-2 min-h-[44px] min-w-[44px] flex items-center justify-center text-gray-400 hover:text-white hover:bg-gray-700 rounded"
          title="Search in document (Ctrl+F)"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </button>
        </div>
      </div>
    );
  }

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
          className="w-full px-3 py-2 bg-gray-700 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none placeholder-gray-500 pr-20 min-h-[44px]"
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
        className="min-h-[44px] min-w-[44px] flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-white text-sm rounded disabled:opacity-30"
        title="Previous match (Shift+Enter)"
      >
        ▲
      </button>
      <button
        onClick={() => goTo(currentIdx + 1)}
        disabled={matchCount === 0}
        className="min-h-[44px] min-w-[44px] flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-white text-sm rounded disabled:opacity-30"
        title="Next match (Enter)"
      >
        ▼
      </button>
      <button
        onClick={handleClose}
        className="min-h-[44px] min-w-[44px] flex items-center justify-center text-gray-400 hover:text-white text-sm"
        title="Close (Escape)"
      >
        ✕
      </button>
    </div>
  );
}
