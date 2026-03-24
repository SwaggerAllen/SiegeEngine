import { create } from 'zustand';

export interface ErrorEntry {
  id: number;
  timestamp: string;
  source: string;
  message: string;
  stack?: string;
}

const STORAGE_KEY = 'siege_error_log';
const MAX_ERRORS = 200;
const KEEP_ON_TRIM = 150;

let nextId = 1;

function loadFromStorage(): ErrorEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const entries: ErrorEntry[] = JSON.parse(raw);
    // Ensure nextId doesn't collide with loaded entries
    const maxId = entries.reduce((max, e) => Math.max(max, e.id), 0);
    if (maxId >= nextId) nextId = maxId + 1;
    return entries;
  } catch {
    return [];
  }
}

function saveToStorage(errors: ErrorEntry[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(errors));
  } catch {
    // localStorage full — trim to half and retry once
    try {
      const trimmed = errors.slice(-Math.floor(errors.length / 2));
      localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
    } catch {
      // give up silently
    }
  }
}

interface ErrorLogState {
  errors: ErrorEntry[];
  pushError: (source: string, error: unknown) => void;
  clear: () => void;
}

function extractMessage(error: unknown): { message: string; stack?: string } {
  if (error instanceof Error) {
    return { message: error.message, stack: error.stack };
  }
  if (typeof error === 'string') return { message: error };
  try {
    return { message: JSON.stringify(error) };
  } catch {
    return { message: String(error) };
  }
}

export const useErrorLogStore = create<ErrorLogState>((set) => ({
  errors: loadFromStorage(),

  pushError: (source, error) => {
    const { message, stack } = extractMessage(error);
    const entry: ErrorEntry = {
      id: nextId++,
      timestamp: new Date().toISOString(),
      source,
      message,
      stack,
    };
    set((state) => {
      const prev = state.errors;
      const next = prev.length >= MAX_ERRORS ? [...prev.slice(-KEEP_ON_TRIM), entry] : [...prev, entry];
      saveToStorage(next);
      return { errors: next };
    });
  },

  clear: () => {
    localStorage.removeItem(STORAGE_KEY);
    set({ errors: [] });
  },
}));
