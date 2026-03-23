import { createSafeStore } from './createSafeStore';
import * as pipelineApi from '../api/pipeline';
import type { DAGResponse } from '../types/dag';
import type { Node, Edge } from '@xyflow/react';

/** Shallow-compare two arrays of plain objects by JSON-serialisable fields. */
function nodesEqual(a: Node[], b: Node[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].id !== b[i].id || a[i].type !== b[i].type ||
        a[i].position.x !== b[i].position.x || a[i].position.y !== b[i].position.y) return false;
  }
  return true;
}

function edgesEqual(a: Edge[], b: Edge[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].id !== b[i].id || a[i].source !== b[i].source ||
        a[i].target !== b[i].target || a[i].type !== b[i].type) return false;
  }
  return true;
}

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

export const useDAGStore = createSafeStore<DAGState>('dag', (set, get) => ({
  nodes: [],
  edges: [],
  docNodes: [],
  docEdges: [],
  selectedArtifactId: null,
  selectedStageKey: null,
  editPromptStageKey: null,

  fetchDAG: async (projectId) => {
    const data: DAGResponse = await pipelineApi.getDAG(projectId);
    const newNodes = mapNodes(data);
    const newEdges = mapEdges(data);
    const { nodes, edges } = get();
    const patch: Partial<DAGState> = {};
    if (!nodesEqual(nodes, newNodes)) patch.nodes = newNodes;
    if (!edgesEqual(edges, newEdges)) patch.edges = newEdges;
    if (Object.keys(patch).length > 0) set(patch);
  },

  fetchDocumentsDAG: async (projectId) => {
    const data: DAGResponse = await pipelineApi.getDocumentsDAG(projectId);
    const newNodes = mapNodes(data);
    const newEdges = mapEdges(data);
    const { docNodes, docEdges } = get();
    const patch: Partial<DAGState> = {};
    if (!nodesEqual(docNodes, newNodes)) patch.docNodes = newNodes;
    if (!edgesEqual(docEdges, newEdges)) patch.docEdges = newEdges;
    if (Object.keys(patch).length > 0) set(patch);
  },

  selectArtifact: (id) => set({ selectedArtifactId: id, selectedStageKey: null }),
  selectStage: (key) => set({ selectedStageKey: key, selectedArtifactId: null }),
  setEditPromptStageKey: (key) => set({ editPromptStageKey: key }),
}));
