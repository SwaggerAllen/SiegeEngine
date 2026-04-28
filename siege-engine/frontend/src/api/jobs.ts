import { z } from 'zod';
import api from './client';

/**
 * Generation-queue API — list + mutate the project's `jobs` rows.
 *
 * Distinct from the Phase 11 pending-instruction queue
 * (`/projects/{id}/queue` → `api/queue.ts`). That one is the
 * user-authored change queue. This is the *generation* queue:
 * every `v2.*` background job the worker is processing.
 */

export const JobStatusValues = [
  'queued',
  'running',
  'completed',
  'failed',
  'cancelled',
] as const;
export type JobStatus = (typeof JobStatusValues)[number];

export const JobRowSchema = z.object({
  id: z.string(),
  job_type: z.string(),
  status: z.string(),
  priority: z.number().int(),
  retry_count: z.number().int(),
  max_retries: z.number().int(),
  is_deferred: z.boolean(),
  locked_by: z.string().nullable(),
  locked_at: z.string().nullable(),
  error_message: z.string().nullable(),
  payload: z.record(z.string(), z.unknown()),
  created_at: z.string().nullable(),
  completed_at: z.string().nullable(),
});
export type JobRow = z.infer<typeof JobRowSchema>;

export const JobListResponseSchema = z.object({
  jobs: z.array(JobRowSchema),
  total_returned: z.number().int(),
  status_counts: z.record(z.string(), z.number().int()),
});
export type JobListResponse = z.infer<typeof JobListResponseSchema>;

export interface ListJobsParams {
  status?: JobStatus[] | null;
  jobType?: string | null;
  limit?: number;
}

export async function listJobs(
  projectId: string,
  params: ListJobsParams = {},
): Promise<JobListResponse> {
  const search: Record<string, string> = {};
  if (params.status && params.status.length) {
    search.status = params.status.join(',');
  }
  if (params.jobType) {
    search.job_type = params.jobType;
  }
  if (params.limit !== undefined) {
    search.limit = String(params.limit);
  }
  const r = await api.get(`/projects/${projectId}/jobs`, { params: search });
  return JobListResponseSchema.parse(r.data);
}

const CancelResponseSchema = z.object({
  ok: z.boolean(),
  cancelled: z.boolean(),
  job_id: z.string(),
});

export async function cancelJob(
  projectId: string,
  jobId: string,
): Promise<{ cancelled: boolean }> {
  const r = await api.post(`/projects/${projectId}/jobs/${jobId}/cancel`);
  const parsed = CancelResponseSchema.parse(r.data);
  return { cancelled: parsed.cancelled };
}

const ReprioritizeResponseSchema = z.object({
  ok: z.boolean(),
  job_id: z.string(),
  priority: z.number().int(),
});

export async function reprioritizeJob(
  projectId: string,
  jobId: string,
  priority: number,
): Promise<{ priority: number }> {
  const r = await api.post(`/projects/${projectId}/jobs/${jobId}/reprioritize`, {
    priority,
  });
  const parsed = ReprioritizeResponseSchema.parse(r.data);
  return { priority: parsed.priority };
}

const DeleteResponseSchema = z.object({
  ok: z.boolean(),
  job_id: z.string(),
});

export async function deleteJob(projectId: string, jobId: string): Promise<void> {
  const r = await api.delete(`/projects/${projectId}/jobs/${jobId}`);
  DeleteResponseSchema.parse(r.data);
}
