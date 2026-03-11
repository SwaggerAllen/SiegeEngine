import { create } from 'zustand';
import * as pipelineApi from '../api/pipeline';
import type { DAGResponse } from '../types/dag';
import type { Node, Edge } from '@xyflow/react';

function mapNodes(data: DAGResponse): Node[] {
  return data.nodes.map((n) => ({
    id: n.id,
    type: n.type,
    data: n.data as unknown as Record<string, unknown>,
    position: n.position,
  }));
}

function mapEdges(data: DAGResponse): Edge[] {
  return data.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    type: e.type,
    animated: e.animated,
  }));
}

interface DAGState {
  // Workflow DAG (pipeline tab)
  nodes: Node[];
  edges: Edge[];
  // Documents DAG (documents tab)
  docNodes: Node[];
  docEdges: Edge[];

  selectedArtifactId: string | null;
  selectedStageKey: string | null;
  editPromptStageKey: string | null;

  fetchDAG: (projectId: string) => Promise<void>;
  fetchDocumentsDAG: (projectId: string) => Promise<void>;
  selectArtifact: (id: string | null) => void;
  selectStage: (key: string | null) => void;
  setEditPromptStageKey: (key: string | null) => void;
}

export const useDAGStore = create<DAGState>((set) => ({
  nodes: [],
  edges: [],
  docNodes: [],
  docEdges: [],
  selectedArtifactId: null,
  selectedStageKey: null,
  editPromptStageKey: null,

  fetchDAG: async (projectId) => {
    const data: DAGResponse = await pipelineApi.getDAG(projectId);
    set({ nodes: mapNodes(data), edges: mapEdges(data) });
  },

  fetchDocumentsDAG: async (projectId) => {
    const data: DAGResponse = await pipelineApi.getDocumentsDAG(projectId);
    set({ docNodes: mapNodes(data), docEdges: mapEdges(data) });
  },

  selectArtifact: (id) => set({ selectedArtifactId: id, selectedStageKey: null }),
  selectStage: (key) => set({ selectedStageKey: key, selectedArtifactId: null }),
  setEditPromptStageKey: (key) => set({ editPromptStageKey: key }),
}));
