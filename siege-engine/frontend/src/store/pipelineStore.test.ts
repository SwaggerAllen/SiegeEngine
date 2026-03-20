import { usePipelineStore } from './pipelineStore';
import type { WSEvent } from '../types/pipeline';

vi.mock('../api/pipeline', () => ({
  getPipelineConfig: vi.fn(),
  getPipelineStatus: vi.fn(),
  startPipeline: vi.fn(),
  resumeStage: vi.fn(),
  reviseArtifact: vi.fn(),
  cancelPipeline: vi.fn(),
  listRuns: vi.fn(),
  getRunState: vi.fn(),
  getSnapshot: vi.fn(),
}));

import * as pipelineApi from '../api/pipeline';

import { emptySnapshot } from './pipelineReducer';

const initialState = {
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

    it('updates currentRunNumber from pipeline_completed event', () => {
      usePipelineStore.setState({ isRunning: true, currentRunNumber: null });
      const event: WSEvent = { type: 'pipeline_completed', run_id: 'run-1', run_number: 5 };

      usePipelineStore.getState().updateFromWS(event);

      expect(usePipelineStore.getState().currentRunNumber).toBe(5);
    });

    it('sets isPaused=true and pausedStage on pipeline_paused event', () => {
      usePipelineStore.setState({ isRunning: true });
      const event: WSEvent = { type: 'pipeline_paused', stage_key: 'extract_components', run_id: 'run-1' };

      usePipelineStore.getState().updateFromWS(event);

      const state = usePipelineStore.getState();
      expect(state.isPaused).toBe(true);
      expect(state.pausedStage).toBe('extract_components');
    });

    it('does not change isRunning on stage_failed event', () => {
      // Set snapshot as running so the reducer preserves it
      usePipelineStore.setState({
        isRunning: true,
        isPaused: false,
        snapshot: { ...emptySnapshot(), is_running: true },
      });
      const event: WSEvent = { type: 'stage_failed', stage_key: 'design', error: 'timeout' };

      usePipelineStore.getState().updateFromWS(event);

      const state = usePipelineStore.getState();
      expect(state.isRunning).toBe(true);
      expect(state.isPaused).toBe(false);
    });
  });

  describe('startPipeline', () => {
    it('sets isRunning=true and calls API with options', async () => {
      vi.mocked(pipelineApi.startPipeline).mockResolvedValue({ run_number: 1, run_id: 'r-1' });
      vi.mocked(pipelineApi.listRuns).mockResolvedValue([
        { id: 'r1', run_number: 1, run_id: 'r-1', status: 'running', human_review: true, ai_loops: 2, stop_point: 'after_all', git_commit_sha: null, started_at: '2024-01-01', completed_at: null },
      ]);

      const options = { human_review: true, ai_loops: 2, stop_point: 'after_all' };
      await usePipelineStore.getState().startPipeline('proj-1', options);

      // Allow fetchRuns to settle
      await vi.waitFor(() => {
        expect(pipelineApi.listRuns).toHaveBeenCalled();
      });

      expect(usePipelineStore.getState().isRunning).toBe(true);
      expect(usePipelineStore.getState().currentRunNumber).toBe(1);
      expect(pipelineApi.startPipeline).toHaveBeenCalledWith('proj-1', options);
    });

    it('resets isRunning=false if API call fails', async () => {
      vi.mocked(pipelineApi.startPipeline).mockRejectedValue(new Error('fail'));

      await expect(
        usePipelineStore.getState().startPipeline('proj-1', { human_review: false, ai_loops: 1, stop_point: 'after_all' })
      ).rejects.toThrow('fail');

      expect(usePipelineStore.getState().isRunning).toBe(false);
    });
  });

  describe('cancelPipeline', () => {
    it('calls API and fetches updated state', async () => {
      usePipelineStore.setState({ isRunning: true, isPaused: true, pausedStage: 'design' });
      vi.mocked(pipelineApi.cancelPipeline).mockResolvedValue({ status: 'cancelled' });
      vi.mocked(pipelineApi.listRuns).mockResolvedValue([]);
      vi.mocked(pipelineApi.getPipelineStatus).mockResolvedValue({
        stages: [],
        snapshot: { ...emptySnapshot(), is_running: false, is_paused: false, paused_stage: null },
      });

      await usePipelineStore.getState().cancelPipeline('proj-1');

      expect(pipelineApi.cancelPipeline).toHaveBeenCalledWith('proj-1', undefined);
      // isRunning/isPaused now updated via fetchStatus which reads snapshot
      await vi.waitFor(() => {
        expect(pipelineApi.getPipelineStatus).toHaveBeenCalled();
      });
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

    it('does not clear paused state for save_feedback action', async () => {
      usePipelineStore.setState({ isPaused: true, pausedStage: 'design' });
      vi.mocked(pipelineApi.resumeStage).mockResolvedValue(undefined);

      await usePipelineStore.getState().resumeStage('proj-1', 'exec-1', 'save_feedback', 'some notes');

      const state = usePipelineStore.getState();
      expect(state.isPaused).toBe(true);
      expect(state.pausedStage).toBe('design');
    });
  });

  describe('fetchRuns', () => {
    it('populates runs and detects active run number', async () => {
      const runs = [
        { id: 'r2', run_number: 2, run_id: 'rid-2', status: 'running' as const, human_review: true, ai_loops: 1, stop_point: 'after_all', git_commit_sha: null, started_at: '2024-01-02', completed_at: null },
        { id: 'r1', run_number: 1, run_id: 'rid-1', status: 'completed' as const, human_review: true, ai_loops: 1, stop_point: 'after_all', git_commit_sha: 'abc123', started_at: '2024-01-01', completed_at: '2024-01-01' },
      ];
      vi.mocked(pipelineApi.listRuns).mockResolvedValue(runs);

      await usePipelineStore.getState().fetchRuns('proj-1');

      const state = usePipelineStore.getState();
      expect(state.runs).toEqual(runs);
      expect(state.currentRunNumber).toBe(2);
      // isRunning/isPaused now derived from snapshot, not from fetchRuns
    });
  });

  describe('selectRun', () => {
    it('fetches historical state when selecting a run', async () => {
      const mockState = { run_number: 1, artifacts: [] };
      vi.mocked(pipelineApi.getRunState).mockResolvedValue(mockState);

      await usePipelineStore.getState().selectRun('proj-1', 1);

      const state = usePipelineStore.getState();
      expect(state.selectedRunNumber).toBe(1);
      expect(state.historicalState).toEqual(mockState);
      expect(state.isViewingHistory).toBe(true);
    });

    it('clears history when selecting null (live view)', async () => {
      usePipelineStore.setState({ selectedRunNumber: 1, historicalState: {}, isViewingHistory: true });

      await usePipelineStore.getState().selectRun('proj-1', null);

      const state = usePipelineStore.getState();
      expect(state.selectedRunNumber).toBeNull();
      expect(state.historicalState).toBeNull();
      expect(state.isViewingHistory).toBe(false);
    });
  });

  describe('reset', () => {
    it('clears all state to initial values', () => {
      usePipelineStore.setState({
        isRunning: true, isPaused: true, pausedStage: 'x',
        executions: [{ id: '1' } as never],
        currentRunNumber: 3, runs: [{ id: 'r' } as never],
        selectedRunNumber: 1, historicalState: {}, isViewingHistory: true,
      });

      usePipelineStore.getState().reset();

      const state = usePipelineStore.getState();
      expect(state.config).toBeNull();
      expect(state.executions).toEqual([]);
      expect(state.isRunning).toBe(false);
      expect(state.isPaused).toBe(false);
      expect(state.pausedStage).toBeNull();
      expect(state.currentRunNumber).toBeNull();
      expect(state.runs).toEqual([]);
      expect(state.selectedRunNumber).toBeNull();
      expect(state.historicalState).toBeNull();
      expect(state.isViewingHistory).toBe(false);
    });
  });
});
