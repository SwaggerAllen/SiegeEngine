export interface DAGNodeData {
  label: string;
  artifact_type: string;
  status: string;
  component_key: string | null;
  version: number;
}

export interface DAGResponse {
  nodes: Array<{
    id: string;
    type: string;
    data: DAGNodeData;
    position: { x: number; y: number };
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    type: string;
    animated: boolean;
  }>;
}
