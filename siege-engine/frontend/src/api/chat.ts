import api from './client';

export interface ChatArtifact {
  id: string;
  name: string;
  artifact_type: string;
  component_key: string | null;
  file_path: string | null;
  status: string;
}

export async function getChatArtifacts(projectId: string): Promise<ChatArtifact[]> {
  const { data } = await api.get(`/chat/${projectId}/artifacts`);
  return data;
}
