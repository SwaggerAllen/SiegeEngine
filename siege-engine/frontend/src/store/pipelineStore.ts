import { create } from 'zustand';
import * as pipelineApi from '../api/pipeline';
import type { PipelineConfig, PipelineRun, PipelineStartOptions, StageExecution, WSEvent } from '../types/pipeline';

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
  reset: () => void;
  fetchConfig: (projectId: string) => Promise<void>;
  fetchStatus: (projectId: string) => Promise<void>;
  fetchRuns: (projectId: string) => Promise<void>;
  startPipeline: (projectId: string, options?: PipelineStartOptions) => Promise<void>;
  resumeRun: (projectId: string, options?: PipelineStartOptions) => Promise<void>;
  resumeStage: (projectId: string, executionId: string, action: string, notes?: string, editedContent?: string) => Promise<void>;
  reviseArtifact: (projectId: string, artifactId: string, feedback: string) => Promise<void>;
  cancelPipeline: (projectId: string) => Promise<void>;
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

  reset: () => set({
    config: null, executions: [], isRunning: false, isPaused: false, pausedStage: null,
    currentRunNumber: null, runs: [], selectedRunNumber: null, historicalState: null, isViewingHistory: false,
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
      });
    } catch (err) {
      console.error('[Pipeline] Failed to fetch runs:', err);
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

  cancelPipeline: async (projectId) => {
    await pipelineApi.cancelPipeline(projectId);
    set({ isRunning: false, isPaused: false, pausedStage: null });
    get().fetchRuns(projectId);
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
