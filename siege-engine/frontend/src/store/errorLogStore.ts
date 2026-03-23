import { create } from 'zustand';

export interface ErrorEntry {
  id: number;
  timestamp: string;
  source: string;
  message: string;
  stack?: string;
}

let nextId = 1;

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
  errors: [],

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
      const next = prev.length >= 200 ? [...prev.slice(-150), entry] : [...prev, entry];
      return { errors: next };
    });
  },

  clear: () => set({ errors: [] }),
}));
