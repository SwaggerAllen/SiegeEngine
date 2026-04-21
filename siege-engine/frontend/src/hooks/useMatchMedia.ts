import { useEffect, useState } from 'react';

/**
 * Subscribe to a ``matchMedia`` query. Returns the current
 * ``matches`` boolean, updates on media changes.
 *
 * Tests that render components using this hook should monkey-
 * patch ``window.matchMedia`` before mount — jsdom's default
 * implementation returns ``false`` for every query, which is
 * usually the right "desktop viewport" default.
 */
export function useMatchMedia(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return false;
    }
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    const mql = window.matchMedia(query);
    const onChange = (e: MediaQueryListEvent) => setMatches(e.matches);
    // Set initial state in case the query's value changed between
    // render and effect run.
    setMatches(mql.matches);
    // Some browsers only implement the legacy addListener API.
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    }
    // Legacy fallback for older browsers without addEventListener.
    const legacy = mql as unknown as {
      addListener: (cb: (e: MediaQueryListEvent) => void) => void;
      removeListener: (cb: (e: MediaQueryListEvent) => void) => void;
    };
    legacy.addListener(onChange);
    return () => legacy.removeListener(onChange);
  }, [query]);

  return matches;
}

/** Convenience: true when the viewport is ≤ 768 px wide. */
export function useIsNarrowViewport(): boolean {
  return useMatchMedia('(max-width: 768px)');
}
