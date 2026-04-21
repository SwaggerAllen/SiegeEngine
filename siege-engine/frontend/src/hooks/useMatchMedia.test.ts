import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useMatchMedia, useIsNarrowViewport } from './useMatchMedia';

function mockMatchMedia(matches: boolean) {
  const listeners = new Set<(e: MediaQueryListEvent) => void>();
  const mql = {
    matches,
    media: '',
    onchange: null,
    addEventListener: (_ev: string, cb: (e: MediaQueryListEvent) => void) => {
      listeners.add(cb);
    },
    removeEventListener: (_ev: string, cb: (e: MediaQueryListEvent) => void) => {
      listeners.delete(cb);
    },
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => true,
  };
  const spy = vi.fn(() => mql as unknown as MediaQueryList);
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: spy,
  });
  return { mql, listeners, spy };
}

afterEach(() => {
  // Reset to a no-op matchMedia so other suites aren't polluted.
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: vi.fn(() => ({
      matches: false,
      media: '',
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => true,
    })),
  });
});

describe('useMatchMedia', () => {
  it('returns the initial matches value from window.matchMedia', () => {
    mockMatchMedia(true);
    const { result } = renderHook(() => useMatchMedia('(max-width: 768px)'));
    expect(result.current).toBe(true);
  });

  it('returns false when matchMedia returns false', () => {
    mockMatchMedia(false);
    const { result } = renderHook(() => useMatchMedia('(max-width: 768px)'));
    expect(result.current).toBe(false);
  });
});

describe('useIsNarrowViewport', () => {
  it('is true when matchMedia reports a narrow viewport', () => {
    mockMatchMedia(true);
    const { result } = renderHook(() => useIsNarrowViewport());
    expect(result.current).toBe(true);
  });
});
