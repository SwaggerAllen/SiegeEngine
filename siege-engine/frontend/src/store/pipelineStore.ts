import { create } from 'zustand';
import * as pipelineApi from '../api/pipeline';
import type { PipelineConfig, PipelineRun, PipelineStartOptions, StageExecution, WSEvent } from '../types/pipeline';

export interface BlockingPR {
  url: string;
  number: number;
}

interface PipelineState {
  config: PipelineConfig | null;
  executions: StageExecution[];
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
  cancelPipeline: (projectId: string, options?: { open_pr?: boolean; pr_title?: string; pr_body?: string; base_branch?: string }) => Promise<void>;
  checkBlockingPR: (projectId: string) => Promise<boolean>;
  dismissBlockingPR: (projectId: string) => Promise<void>;
  retryStage: (projectId: string, executionId: string) => Promise<void>;
  forceRestartStage: (projectId: string, executionId: string) => Promise<void>;
  selectRun: (projectId: string, runNumber: number | null) => Promise<void>;
  updateFromWS: (event: WSEvent) => void;
}

export const usePipelineStore = create<PipelineState>((set, get) => ({
  config: null,
  executions: [],
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

  reset: () => set({
    config: null, executions: [], isRunning: false, isPaused: false, pausedStage: null,
    currentRunNumber: null, runs: [], selectedRunNumber: null, historicalState: null, isViewingHistory: false, lastWSEvent: null, blockingPR: null,
  }),

  fetchConfig: async (projectId) => {
    const config = await pipelineApi.getPipelineConfig(projectId);
    set({ config });
  },

  fetchStatus: async (projectId) => {
    const { stages } = await pipelineApi.getPipelineStatus(projectId);
    set({ executions: stages });
  },

  fetchRuns: async (projectId) => {
    try {
      const runs = await pipelineApi.listRuns(projectId);
      const activeRun = runs.find((r: PipelineRun) => r.status === 'running' || r.status === 'paused');
      set({
        runs,
        currentRunNumber: activeRun?.run_number ?? (runs.length > 0 ? runs[0].run_number : null),
        isRunning: activeRun?.status === 'running' || activeRun?.status === 'paused',
        isPaused: activeRun?.status === 'paused',
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
    set({ isPaused: false, pausedStage: null });
  },

  reviseArtifact: async (projectId, artifactId, feedback) => {
    set({ isRunning: true });
    await pipelineApi.reviseArtifact(projectId, artifactId, feedback);
  },

  resolveStale: async (projectId, artifactId, action, notes, editedContent) => {
    await pipelineApi.resolveStale(projectId, artifactId, action, notes, editedContent);
    if (action === 'rejected') {
      set({ isRunning: true });
    }
  },

  cancelPipeline: async (projectId, options) => {
    const result = await pipelineApi.cancelPipeline(projectId, options);
    set({ isRunning: false, isPaused: false, pausedStage: null });
    if (result.pr_url) {
      set({ blockingPR: { url: result.pr_url, number: result.pr_number } });
    }
    get().fetchRuns(projectId);
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

  retryStage: async (projectId, executionId) => {
    await pipelineApi.retryStage(projectId, executionId);
    set({ isRunning: true });
    get().fetchStatus(projectId);
  },

  forceRestartStage: async (projectId, executionId) => {
    await pipelineApi.forceRestartStage(projectId, executionId);
    set({ isRunning: true });
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

    switch (event.type) {
      case 'stage_started':
        set({ isRunning: true, isPaused: false, pausedStage: null });
        break;
      case 'pipeline_completed':
        set((state) => ({
          isRunning: false,
          isPaused: false,
          pausedStage: null,
          currentRunNumber: event.run_number ?? state.currentRunNumber,
        }));
        break;
      case 'pipeline_paused':
        set({ isPaused: true, pausedStage: event.stage_key });
        break;
      case 'stage_failed':
        // Refresh executions on next render
        break;
    }
  },
}));
