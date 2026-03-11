import { usePipelineStore } from './pipelineStore';
import type { WSEvent } from '../types/pipeline';

vi.mock('../api/pipeline', () => ({
  getPipelineConfig: vi.fn(),
  getPipelineStatus: vi.fn(),
  startPipeline: vi.fn(),
  resumeStage: vi.fn(),
  reviseArtifact: vi.fn(),
  cancelPipeline: vi.fn(),
}));

import * as pipelineApi from '../api/pipeline';

const initialState = {
  config: null,
  executions: [],
  isRunning: false,
  isPaused: false,
  pausedStage: null,
};

describe('pipelineStore', () => {
  beforeEach(() => {
    usePipelineStore.setState(initialState);
    vi.clearAllMocks();
  });

  describe('updateFromWS', () => {
    it('sets isRunning=true on stage_started event', () => {
      const event: WSEvent = { type: 'stage_started', stage_key: 'design' };

      usePipelineStore.getState().updateFromWS(event);

      const state = usePipelineStore.getState();
      expect(state.isRunning).toBe(true);
      expect(state.isPaused).toBe(false);
      expect(state.pausedStage).toBeNull();
    });

    it('sets isRunning=false on pipeline_completed event', () => {
      usePipelineStore.setState({ isRunning: true });
      const event: WSEvent = { type: 'pipeline_completed', run_id: 'run-1' };

      usePipelineStore.getState().updateFromWS(event);

      const state = usePipelineStore.getState();
      expect(state.isRunning).toBe(false);
      expect(state.isPaused).toBe(false);
      expect(state.pausedStage).toBeNull();
    });

    it('sets isPaused=true and pausedStage on pipeline_paused event', () => {
      usePipelineStore.setState({ isRunning: true });
      const event: WSEvent = { type: 'pipeline_paused', stage_key: 'extract_components', run_id: 'run-1' };

      usePipelineStore.getState().updateFromWS(event);

      const state = usePipelineStore.getState();
      expect(state.isPaused).toBe(true);
      expect(state.pausedStage).toBe('extract_components');
    });

    it('does not change state on stage_failed event', () => {
      usePipelineStore.setState({ isRunning: true, isPaused: false });
      const event: WSEvent = { type: 'stage_failed', stage_key: 'design', error: 'timeout' };

      usePipelineStore.getState().updateFromWS(event);

      const state = usePipelineStore.getState();
      expect(state.isRunning).toBe(true);
      expect(state.isPaused).toBe(false);
    });
  });

  describe('startPipeline', () => {
    it('sets isRunning=true and calls API with mode', async () => {
      vi.mocked(pipelineApi.startPipeline).mockResolvedValue(undefined);

      await usePipelineStore.getState().startPipeline('proj-1', 'gated');

      expect(usePipelineStore.getState().isRunning).toBe(true);
      expect(pipelineApi.startPipeline).toHaveBeenCalledWith('proj-1', 'gated');
    });

    it('resets isRunning=false if API call fails', async () => {
      vi.mocked(pipelineApi.startPipeline).mockRejectedValue(new Error('fail'));

      await expect(
        usePipelineStore.getState().startPipeline('proj-1', 'async')
      ).rejects.toThrow('fail');

      expect(usePipelineStore.getState().isRunning).toBe(false);
    });
  });

  describe('cancelPipeline', () => {
    it('resets all running state', async () => {
      usePipelineStore.setState({ isRunning: true, isPaused: true, pausedStage: 'design' });
      vi.mocked(pipelineApi.cancelPipeline).mockResolvedValue(undefined);

      await usePipelineStore.getState().cancelPipeline('proj-1');

      const state = usePipelineStore.getState();
      expect(state.isRunning).toBe(false);
      expect(state.isPaused).toBe(false);
      expect(state.pausedStage).toBeNull();
      expect(pipelineApi.cancelPipeline).toHaveBeenCalledWith('proj-1');
    });
  });

  describe('resumeStage', () => {
    it('calls API and clears paused state', async () => {
      usePipelineStore.setState({ isPaused: true, pausedStage: 'design' });
      vi.mocked(pipelineApi.resumeStage).mockResolvedValue(undefined);

      await usePipelineStore.getState().resumeStage('proj-1', 'exec-1', 'approved', 'looks good');

      const state = usePipelineStore.getState();
      expect(state.isPaused).toBe(false);
      expect(state.pausedStage).toBeNull();
      expect(pipelineApi.resumeStage).toHaveBeenCalledWith('proj-1', 'exec-1', 'approved', 'looks good', undefined);
    });
  });

  describe('reset', () => {
    it('clears all state to initial values', () => {
      usePipelineStore.setState({ isRunning: true, isPaused: true, pausedStage: 'x', executions: [{ id: '1' } as never] });

      usePipelineStore.getState().reset();

      const state = usePipelineStore.getState();
      expect(state.config).toBeNull();
      expect(state.executions).toEqual([]);
      expect(state.isRunning).toBe(false);
      expect(state.isPaused).toBe(false);
      expect(state.pausedStage).toBeNull();
    });
  });
});
