import api from './client';

export interface CommentAuthor {
  id: string;
  username: string;
}

export interface Comment {
  id: string;
  artifact_id: string;
  project_id: string;
  author: CommentAuthor | null;
  content: string;
  comment_type: 'comment' | 'system_event' | 'feedback';
  parent_id: string | null;
  artifact_version: number | null;
  created_at: string;
}

export async function listComments(
  projectId: string,
  artifactId: string,
): Promise<Comment[]> {
  const { data } = await api.get(
    `/comments/${projectId}/artifacts/${artifactId}/comments`,
  );
  return data;
}

export async function createComment(
  projectId: string,
  artifactId: string,
  content: string,
  parentId?: string,
): Promise<Comment> {
  const { data } = await api.post(
    `/comments/${projectId}/artifacts/${artifactId}/comments`,
    { content, parent_id: parentId ?? null },
  );
  return data;
}
