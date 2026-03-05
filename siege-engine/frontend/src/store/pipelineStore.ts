import { create } from 'zustand';
import * as pipelineApi from '../api/pipeline';
import type { PipelineConfig, StageExecution, WSEvent } from '../types/pipeline';

interface PipelineState {
  config: PipelineConfig | null;
  executions: StageExecution[];
  isRunning: boolean;
  isPaused: boolean;
  pausedStage: string | null;
  reset: () => void;
  fetchConfig: (projectId: string) => Promise<void>;
  fetchStatus: (projectId: string) => Promise<void>;
  startPipeline: (projectId: string, mode?: string) => Promise<void>;
  resumeStage: (projectId: string, executionId: string, action: string, notes?: string, editedContent?: string) => Promise<void>;
  reviseArtifact: (projectId: string, artifactId: string, feedback: string) => Promise<void>;
  cancelPipeline: (projectId: string) => Promise<void>;
  updateFromWS: (event: WSEvent) => void;
}

export const usePipelineStore = create<PipelineState>((set) => ({
  config: null,
  executions: [],
  isRunning: false,
  isPaused: false,
  pausedStage: null,

  reset: () => set({ config: null, executions: [], isRunning: false, isPaused: false, pausedStage: null }),

  fetchConfig: async (projectId) => {
    const config = await pipelineApi.getPipelineConfig(projectId);
    set({ config });
  },

  fetchStatus: async (projectId) => {
    const { stages } = await pipelineApi.getPipelineStatus(projectId);
    set({ executions: stages });
  },

  startPipeline: async (projectId, mode) => {
    console.log('[Pipeline] Starting pipeline:', projectId, 'mode:', mode);
    set({ isRunning: true, isPaused: false, pausedStage: null });
    try {
      const result = await pipelineApi.startPipeline(projectId, mode);
      console.log('[Pipeline] Start response:', result);
    } catch (err) {
      console.error('[Pipeline] Start failed:', err);
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
  },

  updateFromWS: (event) => {
    switch (event.type) {
      case 'stage_started':
        set({ isRunning: true, isPaused: false, pausedStage: null });
        break;
      case 'pipeline_completed':
        set({ isRunning: false, isPaused: false, pausedStage: null });
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
