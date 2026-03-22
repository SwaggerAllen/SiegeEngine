import { useState, useEffect, useRef, useCallback } from 'react';

const STORAGE_PREFIX = 'siege-draft:';
const SAVE_INTERVAL_MS = 2000;

/**
 * Persists a text draft to localStorage, auto-saving periodically.
 * Restores on mount, clears on explicit clear() call (e.g. after successful submit).
 *
 * @param key Unique key for this draft (e.g. "review-notes:artifact-id")
 * @param initialValue Value to use if no draft exists in storage
 * @returns [value, setValue, clear] — drop-in replacement for useState
 */
export function useLocalDraft(
  key: string,
  initialValue: string = '',
): [string, (v: string | ((prev: string) => string)) => void, () => void] {
  const storageKey = STORAGE_PREFIX + key;

  const [value, setValueRaw] = useState<string>(() => {
    try {
      const stored = localStorage.getItem(storageKey);
      return stored !== null ? stored : initialValue;
    } catch {
      return initialValue;
    }
  });

  // Track the latest value for the save interval without re-registering the timer
  const valueRef = useRef(value);
  const lastSavedRef = useRef(value);

  // When the key changes (switching artifacts), load from storage or reset
  const prevKeyRef = useRef(storageKey);
  useEffect(() => {
    if (prevKeyRef.current !== storageKey) {
      // Flush the old key's value before switching
      try {
        if (lastSavedRef.current !== valueRef.current) {
          if (valueRef.current) {
            localStorage.setItem(prevKeyRef.current, valueRef.current);
          } else {
            localStorage.removeItem(prevKeyRef.current);
          }
        }
      } catch { /* quota exceeded, etc */ }

      prevKeyRef.current = storageKey;
      try {
        const stored = localStorage.getItem(storageKey);
        const next = stored !== null ? stored : initialValue;
        setValueRaw(next);
        valueRef.current = next;
        lastSavedRef.current = next;
      } catch {
        setValueRaw(initialValue);
        valueRef.current = initialValue;
        lastSavedRef.current = initialValue;
      }
    }
  }, [storageKey, initialValue]);

  // Wrap setValue to also update the ref
  const setValue = useCallback(
    (v: string | ((prev: string) => string)) => {
      setValueRaw((prev) => {
        const next = typeof v === 'function' ? v(prev) : v;
        valueRef.current = next;
        return next;
      });
    },
    [],
  );

  // Periodic save
  useEffect(() => {
    const timer = setInterval(() => {
      if (valueRef.current !== lastSavedRef.current) {
        try {
          if (valueRef.current) {
            localStorage.setItem(storageKey, valueRef.current);
          } else {
            localStorage.removeItem(storageKey);
          }
          lastSavedRef.current = valueRef.current;
        } catch { /* quota exceeded */ }
      }
    }, SAVE_INTERVAL_MS);

    return () => {
      clearInterval(timer);
      // Flush on unmount
      if (valueRef.current !== lastSavedRef.current) {
        try {
          if (valueRef.current) {
            localStorage.setItem(storageKey, valueRef.current);
          } else {
            localStorage.removeItem(storageKey);
          }
        } catch { /* ignore */ }
      }
    };
  }, [storageKey]);

  // Clear draft from storage and reset value
  const clear = useCallback(() => {
    try {
      localStorage.removeItem(storageKey);
    } catch { /* ignore */ }
    setValueRaw('');
    valueRef.current = '';
    lastSavedRef.current = '';
  }, [storageKey]);

  return [value, setValue, clear];
}
