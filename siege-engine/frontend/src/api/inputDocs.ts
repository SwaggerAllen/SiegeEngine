import api from './client';

export interface InputDocument {
  id: string;
  name: string;
  content: string;
  doc_type: string;
  inject_into_stages: string[];
  version: number;
  created_at: string;
  updated_at: string;
}

export async function listInputDocs(projectId: string): Promise<InputDocument[]> {
  const { data } = await api.get(`/pipeline/${projectId}/input-docs`);
  return data;
}

export async function createInputDoc(
  projectId: string,
  doc: { name: string; content: string; doc_type?: string; inject_into_stages?: string[] }
): Promise<{ id: string; name: string; version: number }> {
  const { data } = await api.post(`/pipeline/${projectId}/input-docs`, doc);
  return data;
}

export async function updateInputDoc(
  projectId: string,
  docId: string,
  updates: { name?: string; content?: string; doc_type?: string; inject_into_stages?: string[] }
): Promise<{ id: string; name: string; version: number }> {
  const { data } = await api.put(`/pipeline/${projectId}/input-docs/${docId}`, updates);
  return data;
}

export async function deleteInputDoc(projectId: string, docId: string) {
  const { data } = await api.delete(`/pipeline/${projectId}/input-docs/${docId}`);
  return data;
}

export async function propagateChanges(projectId: string) {
  const { data } = await api.post(`/pipeline/${projectId}/propagate`);
  return data;
}
