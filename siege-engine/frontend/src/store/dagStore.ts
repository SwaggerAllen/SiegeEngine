import { create } from 'zustand';
import * as pipelineApi from '../api/pipeline';
import type { DAGResponse } from '../types/dag';
import type { Node, Edge } from '@xyflow/react';

interface DAGState {
  nodes: Node[];
  edges: Edge[];
  selectedArtifactId: string | null;
  fetchDAG: (projectId: string) => Promise<void>;
  selectArtifact: (id: string | null) => void;
}

export const useDAGStore = create<DAGState>((set) => ({
  nodes: [],
  edges: [],
  selectedArtifactId: null,

  fetchDAG: async (projectId) => {
    const data: DAGResponse = await pipelineApi.getDAG(projectId);
    set({
      nodes: data.nodes.map((n) => ({
        id: n.id,
        type: n.type,
        data: n.data as unknown as Record<string, unknown>,
        position: n.position,
      })),
      edges: data.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: e.type,
        animated: e.animated,
      })),
    });
  },

  selectArtifact: (id) => set({ selectedArtifactId: id }),
}));
