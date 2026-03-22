import { create } from 'zustand';
import * as pipelineApi from '../api/pipeline';
import type { PipelineConfig, PipelineRun, PipelineSnapshot, PipelineStartOptions, StageExecution, WSEvent } from '../types/pipeline';
import { applyWSEvent, emptySnapshot } from './pipelineReducer';

export interface BlockingPR {
  url: string;
  number: number;
}

interface PipelineState {
  config: PipelineConfig | null;
  executions: StageExecution[];
  snapshot: PipelineSnapshot;
  isRunning: boolean;
  isPaused: boolean;
  pausedStage: string | null;
  currentRunNumber: number | null;
  runs: PipelineRun[];
  selectedRunNumber: number | null;
  historicalState: Record<string, unknown> | null;
  isViewingHistory: boolean;
  lastWSEvent: WSEvent | null;
  blockingPR: BlockingPR | null;
  logEntries: Array<{ timestamp: string; level: string; logger: string; message: string }>;
  clearLogs: () => void;
  reset: () => void;
  fetchConfig: (projectId: string) => Promise<void>;
  fetchStatus: (projectId: string) => Promise<void>;
  fetchRuns: (projectId: string) => Promise<void>;
  fetchBlockingPR: (projectId: string) => Promise<void>;
  startPipeline: (projectId: string, options?: PipelineStartOptions) => Promise<void>;
  resumeRun: (projectId: string, options?: PipelineStartOptions) => Promise<void>;
  resumeStage: (projectId: string, executionId: string, action: string, notes?: string, editedContent?: string) => Promise<void>;
  reviseArtifact: (projectId: string, artifactId: string, feedback: string) => Promise<void>;
  resolveStale: (projectId: string, artifactId: string, action: string, notes?: string, editedContent?: string) => Promise<void>;
  regenDownstream: (projectId: string, artifactId: string) => Promise<void>;
  cancelPipeline: (projectId: string, options?: { open_pr?: boolean; pr_title?: string; pr_body?: string; base_branch?: string }) => Promise<void>;
  resetAll: (projectId: string) => Promise<void>;
  checkBlockingPR: (projectId: string) => Promise<boolean>;
  dismissBlockingPR: (projectId: string) => Promise<void>;
  cancelStage: (projectId: string, executionId: string) => Promise<void>;
  retryStage: (projectId: string, executionId: string) => Promise<void>;
  forceRestartStage: (projectId: string, executionId: string) => Promise<void>;
  triggerStage: (projectId: string, stageKey: string, componentKey?: string | null) => Promise<void>;
  pruneArtifact: (projectId: string, artifactId: string) => Promise<void>;
  selectRun: (projectId: string, runNumber: number | null) => Promise<void>;
  updateFromWS: (event: WSEvent) => void;
}

export const usePipelineStore = create<PipelineState>((set, get) => ({
  config: null,
  executions: [],
  snapshot: emptySnapshot(),
  isRunning: false,
  isPaused: false,
  pausedStage: null,
  currentRunNumber: null,
  runs: [],
  selectedRunNumber: null,
  historicalState: null,
  isViewingHistory: false,
  lastWSEvent: null,
  blockingPR: null,
  logEntries: [],

  clearLogs: () => set({ logEntries: [] }),

  reset: () => set({
    config: null, executions: [], snapshot: emptySnapshot(), isRunning: false, isPaused: false, pausedStage: null,
    currentRunNumber: null, runs: [], selectedRunNumber: null, historicalState: null, isViewingHistory: false, lastWSEvent: null, blockingPR: null, logEntries: [],
  }),

  fetchConfig: async (projectId) => {
    const config = await pipelineApi.getPipelineConfig(projectId);
    set({ config });
  },

  fetchStatus: async (projectId) => {
    const data = await pipelineApi.getPipelineStatus(projectId);
    const updates: Partial<PipelineState> = { executions: data.stages };
    // Use snapshot as source of truth for running/paused state
    if (data.snapshot) {
      updates.snapshot = data.snapshot;
      updates.isRunning = data.snapshot.is_running;
      updates.isPaused = data.snapshot.is_paused;
      updates.pausedStage = data.snapshot.paused_stage;
    }
    set(updates);
  },

  fetchRuns: async (projectId) => {
    try {
      const runs = await pipelineApi.listRuns(projectId);
      const activeRun = runs.find((r: PipelineRun) => r.status === 'running' || r.status === 'paused');
      set({
        runs,
        currentRunNumber: activeRun?.run_number ?? (runs.length > 0 ? runs[0].run_number : null),
        // isRunning/isPaused now derived from snapshot via fetchStatus and WS events
      });
    } catch (err) {
      console.error('[Pipeline] Failed to fetch runs:', err);
    }
  },

  fetchBlockingPR: async (projectId) => {
    try {
      const data = await pipelineApi.getBlockingPR(projectId);
      set({
        blockingPR: data.blocking_pr_url
          ? { url: data.blocking_pr_url, number: data.blocking_pr_number! }
          : null,
      });
    } catch (err) {
      console.error('[Pipeline] Failed to fetch blocking PR:', err);
    }
  },

  startPipeline: async (projectId, options) => {
    console.log('[Pipeline] Starting pipeline:', projectId, 'options:', options);
    set({ isRunning: true, isPaused: false, pausedStage: null });
    try {
      const result = await pipelineApi.startPipeline(projectId, options);
      console.log('[Pipeline] Start response:', result);
      set({ currentRunNumber: result.run_number });
      // Refresh runs list
      get().fetchRuns(projectId);
    } catch (err) {
      console.error('[Pipeline] Start failed:', err);
      set({ isRunning: false });
      throw err;
    }
  },

  resumeRun: async (projectId, options) => {
    console.log('[Pipeline] Resuming run:', projectId, 'options:', options);
    set({ isRunning: true, isPaused: false, pausedStage: null });
    try {
      const result = await pipelineApi.resumeRun(projectId, options);
      console.log('[Pipeline] Resume run response:', result);
      set({ currentRunNumber: result.run_number });
      get().fetchRuns(projectId);
    } catch (err) {
      console.error('[Pipeline] Resume run failed:', err);
      set({ isRunning: false });
      throw err;
    }
  },

  resumeStage: async (projectId, executionId, action, notes, editedContent) => {
    await pipelineApi.resumeStage(projectId, executionId, action, notes, editedContent);
    if (action !== 'save_feedback') {
      set({ isPaused: false, pausedStage: null });
    }
  },

  reviseArtifact: async (projectId, artifactId, feedback) => {
    await pipelineApi.reviseArtifact(projectId, artifactId, feedback);
  },

  resolveStale: async (projectId, artifactId, action, notes, editedContent) => {
    await pipelineApi.resolveStale(projectId, artifactId, action, notes, editedContent);
    // isRunning will be updated by WS events via the reducer
  },

  regenDownstream: async (projectId, artifactId) => {
    await pipelineApi.regenDownstream(projectId, artifactId);
    // isRunning will be updated by WS events via the reducer
  },

  cancelPipeline: async (projectId, options) => {
    const result = await pipelineApi.cancelPipeline(projectId, options);
    if (result.pr_url) {
      set({ blockingPR: { url: result.pr_url, number: result.pr_number } });
    }
    if (result.pr_error) {
      console.error('[Pipeline] PR creation failed:', result.pr_error);
      throw new Error(result.pr_error);
    }
    // Snapshot reconciles via fetchStatus
    get().fetchRuns(projectId);
    get().fetchStatus(projectId);
  },

  resetAll: async (projectId) => {
    await pipelineApi.resetAll(projectId);
    // Snapshot reconciles via fetchStatus
    get().fetchRuns(projectId);
    get().fetchStatus(projectId);
  },

  checkBlockingPR: async (projectId) => {
    const result = await pipelineApi.checkBlockingPR(projectId);
    if (!result.blocking) {
      set({ blockingPR: null });
      return false;
    }
    return true;
  },

  dismissBlockingPR: async (projectId) => {
    await pipelineApi.dismissBlockingPR(projectId);
    set({ blockingPR: null });
  },

  cancelStage: async (projectId, executionId) => {
    await pipelineApi.cancelStage(projectId, executionId);
    get().fetchStatus(projectId);
  },

  retryStage: async (projectId, executionId) => {
    await pipelineApi.retryStage(projectId, executionId);
    get().fetchStatus(projectId);
  },

  forceRestartStage: async (projectId, executionId) => {
    await pipelineApi.forceRestartStage(projectId, executionId);
    get().fetchStatus(projectId);
  },

  triggerStage: async (projectId, stageKey, componentKey) => {
    await pipelineApi.triggerStage(projectId, stageKey, componentKey);
    get().fetchStatus(projectId);
  },

  pruneArtifact: async (projectId, artifactId) => {
    await pipelineApi.pruneArtifact(projectId, artifactId);
    get().fetchStatus(projectId);
  },

  selectRun: async (projectId, runNumber) => {
    if (runNumber === null) {
      // Switch back to live view
      set({ selectedRunNumber: null, historicalState: null, isViewingHistory: false });
      return;
    }
    try {
      const state = await pipelineApi.getRunState(projectId, runNumber);
      set({ selectedRunNumber: runNumber, historicalState: state, isViewingHistory: true });
    } catch (err) {
      console.error('[Pipeline] Failed to fetch run state:', err);
    }
  },

  updateFromWS: (event) => {
    // Always store the latest event so subscribers (e.g. CommentsPanel) can react
    set({ lastWSEvent: event });

    // Accumulate log entries (keep last 500 to avoid unbounded growth)
    if (event.type === 'log_entry') {
      const prev = get().logEntries;
      const next = prev.length >= 500 ? [...prev.slice(-400), event] : [...prev, event];
      set({ logEntries: next });
      return;  // log_entry doesn't affect pipeline snapshot state
    }

    // Apply event through the reducer to update snapshot + derived state
    const prevSnapshot = get().snapshot;
    const newSnapshot = applyWSEvent(prevSnapshot, event);

    const updates: Partial<PipelineState> = {
      snapshot: newSnapshot,
      isRunning: newSnapshot.is_running,
      isPaused: newSnapshot.is_paused,
      pausedStage: newSnapshot.paused_stage,
    };

    // Update currentRunNumber on pipeline_completed
    if (event.type === 'pipeline_completed' && event.run_number) {
      updates.currentRunNumber = event.run_number;
    }

    set(updates);
  },
}));
