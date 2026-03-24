import { createSafeStore } from './createSafeStore';

interface DAGState {
  selectedArtifactId: string | null;
  selectedStageKey: string | null;
  editPromptStageKey: string | null;

  selectArtifact: (id: string | null) => void;
  selectStage: (key: string | null) => void;
  setEditPromptStageKey: (key: string | null) => void;
  clearSelection: () => void;
}

export const useDAGStore = createSafeStore<DAGState>('dag', (set) => ({
  selectedArtifactId: null,
  selectedStageKey: null,
  editPromptStageKey: null,

  selectArtifact: (id) => set({ selectedArtifactId: id, selectedStageKey: null }),
  selectStage: (key) => set({ selectedStageKey: key, selectedArtifactId: null }),
  setEditPromptStageKey: (key) => set({ editPromptStageKey: key }),
  clearSelection: () => set({ selectedArtifactId: null, selectedStageKey: null }),
}));
