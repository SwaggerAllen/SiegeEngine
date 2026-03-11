import { useDAGStore } from './dagStore';
import type { DAGResponse } from '../types/dag';

vi.mock('../api/pipeline', () => ({
  getDAG: vi.fn(),
  getDocumentsDAG: vi.fn(),
}));

import * as pipelineApi from '../api/pipeline';

const initialState = {
  nodes: [],
  edges: [],
  docNodes: [],
  docEdges: [],
  selectedArtifactId: null,
  selectedStageKey: null,
  editPromptStageKey: null,
};

const mockDAGResponse: DAGResponse = {
  nodes: [
    {
      id: 'node-1',
      type: 'stageNode',
      data: {
        label: 'Requirements',
        artifact_type: 'system_requirements',
        status: 'approved',
        component_key: null,
        version: 1,
        stage_key: 'system_requirements',
        is_active: false,
        has_artifact: true,
      },
      position: { x: 0, y: 0 },
    },
    {
      id: 'node-2',
      type: 'stageNode',
      data: {
        label: 'Architecture',
        artifact_type: 'system_architecture',
        status: 'pending',
        component_key: null,
        version: 0,
        stage_key: 'system_architecture',
        is_active: false,
        has_artifact: false,
      },
      position: { x: 0, y: 100 },
    },
  ],
  edges: [
    {
      id: 'e-1-2',
      source: 'node-1',
      target: 'node-2',
      type: 'default',
      animated: false,
    },
  ],
};

describe('dagStore', () => {
  beforeEach(() => {
    useDAGStore.setState(initialState);
    vi.clearAllMocks();
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

  describe('fetchDAG', () => {
    it('maps API response into ReactFlow nodes and edges', async () => {
      vi.mocked(pipelineApi.getDAG).mockResolvedValue(mockDAGResponse);

      await useDAGStore.getState().fetchDAG('proj-1');

      const state = useDAGStore.getState();
      expect(state.nodes).toHaveLength(2);
      expect(state.edges).toHaveLength(1);
      expect(state.nodes[0].id).toBe('node-1');
      expect(state.nodes[1].id).toBe('node-2');
      expect(state.edges[0].source).toBe('node-1');
      expect(state.edges[0].target).toBe('node-2');
    });
  });

  describe('fetchDocumentsDAG', () => {
    it('maps API response into docNodes and docEdges', async () => {
      vi.mocked(pipelineApi.getDocumentsDAG).mockResolvedValue(mockDAGResponse);

      await useDAGStore.getState().fetchDocumentsDAG('proj-1');

      const state = useDAGStore.getState();
      expect(state.docNodes).toHaveLength(2);
      expect(state.docEdges).toHaveLength(1);
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
