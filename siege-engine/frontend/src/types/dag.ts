export interface PromptInfo {
  stage_key: string;
  model: string | null;
  has_custom_config: boolean;
  template_key: string;
}

export interface DAGNodeData {
  label: string;
  artifact_type: string;
  status: string;
  component_key: string | null;
  version: number;
  stage_key: string;
  is_active: boolean;
  has_artifact: boolean;
  prompt_info?: PromptInfo | null;
  execution_id?: string | null;
  execution_status?: string | null;
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
