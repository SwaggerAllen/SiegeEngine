import api from './client';

/**
 * Project debug snapshot — single-shot dump of every projection
 * table + the recent event tail + the recent job log.
 *
 * The shape is deliberately not Zod-validated because the backend
 * returns large freeform JSON (event payloads, job payloads,
 * fragment metadata) that we don't want to enforce schema on at
 * the wire. The DebugPanel's only contract with this surface is
 * "I can render whatever JSON the backend gives me."
 */

export interface DebugSnapshot {
  project: {
    id: string;
    name: string;
    git_repo_path: string;
    created_at: string | null;
  };
  summary: {
    node_count: number;
    edge_count: number;
    fragment_count: number;
    draft_count: number;
    staleness_rows: number;
    jobs_returned: number;
    events_returned: number;
  };
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  fragments: Array<Record<string, unknown>>;
  drafts: Array<Record<string, unknown>>;
  staleness: Array<Record<string, unknown>>;
  recent_jobs: Array<Record<string, unknown>>;
  recent_events: Array<Record<string, unknown>>;
}

export async function getDebugSnapshot(projectId: string): Promise<DebugSnapshot> {
  const r = await api.get<DebugSnapshot>(`/projects/${projectId}/debug/snapshot`);
  return r.data;
}
