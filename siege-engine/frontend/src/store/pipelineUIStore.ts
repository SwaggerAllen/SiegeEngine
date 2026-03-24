import { create } from 'zustand';
import type { WSEvent } from '../types/pipeline';

export interface LogEntry {
  timestamp: string;
  level: string;
  logger: string;
  message: string;
}

interface PipelineUIState {
  // History view state
  selectedRunNumber: number | null;
  historicalState: Record<string, unknown> | null;
  isViewingHistory: boolean;

  // WebSocket-driven client-only state
  lastWSEvent: WSEvent | null;
  logEntries: LogEntry[];

  // Actions
  setSelectedRun: (runNumber: number | null, state?: Record<string, unknown> | null) => void;
  setLastWSEvent: (event: WSEvent | null) => void;
  addLogEntry: (entry: LogEntry) => void;
  clearLogs: () => void;
  reset: () => void;
}

export const usePipelineUIStore = create<PipelineUIState>((set, get) => ({
  selectedRunNumber: null,
  historicalState: null,
  isViewingHistory: false,
  lastWSEvent: null,
  logEntries: [],

  setSelectedRun: (runNumber, state = null) =>
    set({
      selectedRunNumber: runNumber,
      historicalState: state,
      isViewingHistory: runNumber !== null,
    }),

  setLastWSEvent: (event) => set({ lastWSEvent: event }),

  addLogEntry: (entry) => {
    const prev = get().logEntries;
    const next = prev.length >= 500 ? [...prev.slice(-400), entry] : [...prev, entry];
    set({ logEntries: next });
  },

  clearLogs: () => set({ logEntries: [] }),

  reset: () =>
    set({
      selectedRunNumber: null,
      historicalState: null,
      isViewingHistory: false,
      lastWSEvent: null,
      logEntries: [],
    }),
}));
