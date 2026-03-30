import { z } from 'zod';
import api from './client';
import { CommentSchema } from '../schemas/comments';
import type { Comment } from '../schemas/comments';

export type { Comment, CommentAuthor } from '../schemas/comments';

export async function listComments(
  projectId: string,
  artifactId: string,
): Promise<Comment[]> {
  const { data } = await api.get(
    `/comments/${projectId}/artifacts/${artifactId}/comments`,
  );
  return z.array(CommentSchema).parse(data);
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
  return CommentSchema.parse(data);
}

export async function updateComment(
  projectId: string,
  artifactId: string,
  commentId: string,
  content: string,
): Promise<Comment> {
  const { data } = await api.put(
    `/comments/${projectId}/artifacts/${artifactId}/comments/${commentId}`,
    { content },
  );
  return CommentSchema.parse(data);
}

export async function saveFeedback(
  projectId: string,
  artifactId: string,
  content: string,
  editedContent?: string,
): Promise<Comment> {
  const { data } = await api.post(
    `/comments/${projectId}/artifacts/${artifactId}/feedback`,
    { content, edited_content: editedContent ?? null },
  );
  return CommentSchema.parse(data);
}

export async function deleteComment(
  projectId: string,
  artifactId: string,
  commentId: string,
): Promise<void> {
  await api.delete(
    `/comments/${projectId}/artifacts/${artifactId}/comments/${commentId}`,
  );
}
