import { z } from 'zod';

export const InputDocumentSchema = z.object({
  id: z.string(),
  name: z.string(),
  content: z.string(),
  doc_type: z.string(),
  inject_into_stages: z.array(z.string()),
  version: z.number(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type InputDocument = z.infer<typeof InputDocumentSchema>;
