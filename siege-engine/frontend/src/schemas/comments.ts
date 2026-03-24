import { z } from 'zod';

export const CommentAuthorSchema = z.object({
  id: z.string(),
  username: z.string(),
});

export const CommentSchema = z.object({
  id: z.string(),
  artifact_id: z.string(),
  project_id: z.string(),
  author: CommentAuthorSchema.nullable(),
  content: z.string(),
  comment_type: z.enum(['comment', 'system_event', 'feedback']),
  parent_id: z.string().nullable(),
  artifact_version: z.number().nullable(),
  created_at: z.string(),
  updated_at: z.string().nullable(),
});

export type CommentAuthor = z.infer<typeof CommentAuthorSchema>;
export type Comment = z.infer<typeof CommentSchema>;
