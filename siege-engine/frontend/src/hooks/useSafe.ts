/**
 * Safe hook wrappers — the hooks equivalent of createSafeStore.
 *
 * React error boundaries only catch errors during render. Errors in
 * useEffect, useMemo, event handlers, and callbacks are NOT caught.
 * These wrappers catch those errors, log them to errorLogStore, and
 * return safe fallbacks instead of letting the error crash the page.
 */
import { useEffect, useMemo, useCallback, useRef, type DependencyList } from 'react';
import { useErrorLogStore } from '../store/errorLogStore';

/**
 * useEffect that catches synchronous throws inside the effect body.
 * Async errors from fire-and-forget promises inside effects are already
 * handled by the global unhandledrejection listener in main.tsx.
 */
export function useSafeEffect(
  label: string,
  effect: () => void | (() => void),
  deps: DependencyList,
) {
  const labelRef = useRef(label);
  labelRef.current = label;

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    try {
      return effect();
    } catch (err) {
      console.error(`[useSafeEffect:${labelRef.current}]`, err);
      useErrorLogStore.getState().pushError(`useSafeEffect(${labelRef.current})`, err);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/**
 * useMemo that returns a fallback value if the factory throws.
 */
export function useSafeMemo<T>(
  label: string,
  factory: () => T,
  fallback: T,
  deps: DependencyList,
): T {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => {
    try {
      return factory();
    } catch (err) {
      console.error(`[useSafeMemo:${label}]`, err);
      useErrorLogStore.getState().pushError(`useSafeMemo(${label})`, err);
      return fallback;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/**
 * useCallback that catches errors thrown by the callback.
 * For async callbacks, the returned promise still rejects so callers
 * with try/catch can handle it, but the error is also logged.
 */
export function useSafeCallback<T extends (...args: never[]) => unknown>(
  label: string,
  callback: T,
  deps: DependencyList,
): T {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useCallback((...args: Parameters<T>) => {
    try {
      const result = callback(...args);
      if (result instanceof Promise) {
        return result.catch((err: unknown) => {
          console.error(`[useSafeCallback:${label}]`, err);
          useErrorLogStore.getState().pushError(`useSafeCallback(${label})`, err);
          throw err; // re-throw so callers with try/catch still receive it
        });
      }
      return result;
    } catch (err) {
      console.error(`[useSafeCallback:${label}]`, err);
      useErrorLogStore.getState().pushError(`useSafeCallback(${label})`, err);
      throw err; // re-throw so callers receive the error (consistent with async path)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps) as T;
}
