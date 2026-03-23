/**
 * Zustand store wrapper that makes all async actions safe by default.
 *
 * Every function returned by the store initializer is wrapped so that:
 *  1. If it returns a Promise, a .catch() is attached that logs the error
 *     to errorLogStore with the store name and action name.
 *  2. The ORIGINAL promise is returned to callers — so callers with
 *     try/catch still receive the error.
 *  3. The .catch() we attach marks the rejection as "handled" in the JS
 *     engine, so fire-and-forget callers don't trigger unhandledrejection.
 *
 * This means new store actions are safe automatically — no manual .catch()
 * needed at call sites.
 */
import { create } from 'zustand';
import type { StateCreator } from 'zustand';
import { useErrorLogStore } from './errorLogStore';

export function createSafeStore<T>(
  name: string,
  initializer: StateCreator<T>,
) {
  return create<T>((set, get, api) => {
    const state = initializer(set, get, api);
    const wrapped: Record<string, unknown> = {};

    for (const [key, value] of Object.entries(state as Record<string, unknown>)) {
      if (typeof value !== 'function') {
        wrapped[key] = value;
        continue;
      }

      const fn = value as (...args: unknown[]) => unknown;
      wrapped[key] = (...args: unknown[]) => {
        try {
          const result = fn(...args);
          if (result instanceof Promise) {
            // Attach a catch handler to mark the rejection as "handled".
            // This prevents unhandledrejection for fire-and-forget callers.
            // Return the ORIGINAL promise so callers with try/catch still
            // receive the error.
            result.catch((err: unknown) => {
              useErrorLogStore.getState().pushError(`${name}.${key}`, err);
            });
          }
          return result;
        } catch (err) {
          useErrorLogStore.getState().pushError(`${name}.${key}`, err);
          throw err;
        }
      };
    }

    return wrapped as T;
  });
}
