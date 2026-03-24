import { z } from 'zod';
import api from './client';
import { InputDocumentSchema } from '../schemas/inputDocs';
import type { InputDocument } from '../schemas/inputDocs';

export type { InputDocument } from '../schemas/inputDocs';

export async function listInputDocs(projectId: string): Promise<InputDocument[]> {
  const { data } = await api.get(`/pipeline/${projectId}/input-docs`);
  return z.array(InputDocumentSchema).parse(data);
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
  const { data } = await api.post(`/pipeline/${projectId}/action`, { type: 'propagate' });
  return data;
}
