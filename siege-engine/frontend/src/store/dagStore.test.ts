import { useDAGStore } from './dagStore';

const initialState = {
  selectedArtifactId: null,
  selectedStageKey: null,
  editPromptStageKey: null,
};

describe('dagStore', () => {
  beforeEach(() => {
    useDAGStore.setState(initialState);
  });

  describe('selectArtifact', () => {
    it('sets selectedArtifactId and clears selectedStageKey', () => {
      useDAGStore.setState({ selectedStageKey: 'some-stage' });

      useDAGStore.getState().selectArtifact('artifact-1');

      const state = useDAGStore.getState();
      expect(state.selectedArtifactId).toBe('artifact-1');
      expect(state.selectedStageKey).toBeNull();
    });

    it('sets selectedArtifactId to null when called with null', () => {
      useDAGStore.setState({ selectedArtifactId: 'art-1' });

      useDAGStore.getState().selectArtifact(null);

      expect(useDAGStore.getState().selectedArtifactId).toBeNull();
    });
  });

  describe('selectStage', () => {
    it('sets selectedStageKey and clears selectedArtifactId', () => {
      useDAGStore.setState({ selectedArtifactId: 'art-1' });

      useDAGStore.getState().selectStage('design');

      const state = useDAGStore.getState();
      expect(state.selectedStageKey).toBe('design');
      expect(state.selectedArtifactId).toBeNull();
    });
  });

  describe('clearSelection', () => {
    it('clears both selectedArtifactId and selectedStageKey', () => {
      useDAGStore.setState({ selectedArtifactId: 'art-1', selectedStageKey: 'stage-1' });

      useDAGStore.getState().clearSelection();

      const state = useDAGStore.getState();
      expect(state.selectedArtifactId).toBeNull();
      expect(state.selectedStageKey).toBeNull();
    });
  });

  describe('mutual exclusivity invariant', () => {
    it('selecting artifact then stage then artifact produces correct state each time', () => {
      useDAGStore.getState().selectArtifact('a1');
      expect(useDAGStore.getState().selectedArtifactId).toBe('a1');
      expect(useDAGStore.getState().selectedStageKey).toBeNull();

      useDAGStore.getState().selectStage('s1');
      expect(useDAGStore.getState().selectedStageKey).toBe('s1');
      expect(useDAGStore.getState().selectedArtifactId).toBeNull();

      useDAGStore.getState().selectArtifact('a2');
      expect(useDAGStore.getState().selectedArtifactId).toBe('a2');
      expect(useDAGStore.getState().selectedStageKey).toBeNull();
    });
  });

  describe('setEditPromptStageKey', () => {
    it('sets and clears the editPromptStageKey', () => {
      useDAGStore.getState().setEditPromptStageKey('design');
      expect(useDAGStore.getState().editPromptStageKey).toBe('design');

      useDAGStore.getState().setEditPromptStageKey(null);
      expect(useDAGStore.getState().editPromptStageKey).toBeNull();
    });
  });
});
