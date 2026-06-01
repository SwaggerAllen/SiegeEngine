/**
 * Axios client for the v3 siege HTTP server, mounted at /siege/ on the
 * deployed FastAPI app. The legacy backend's /api/* and the new
 * /siege/api/* both authenticate with the same JWT, but the baseURL
 * differs, so they ride on separate axios instances.
 */

import axios from 'axios';

const siegeApi = axios.create({
  baseURL: '/siege/api',
  headers: { 'Content-Type': 'application/json' },
});

siegeApi.interceptors.request.use((config) => {
  const token = localStorage.getItem('siege_engine_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export interface V3Node {
  id: string;
  tier: string;
  kind: string;
  name: string;
  parent_id: string | null;
  order: number;
  is_foundation: boolean;
  implicit: boolean;
  status: string;
  score: number | null;
  has_body: boolean;
}

export interface V3Edge {
  id: string;
  type: string;
  source_id: string;
  target_id: string;
}

export interface ProjectGraph {
  ref: string;
  ref_head_sha: string;
  nodes: V3Node[];
  edges: V3Edge[];
}

export async function getProjectGraph(projectId: string, ref = 'main'): Promise<ProjectGraph> {
  const { data } = await siegeApi.post('/get-project-graph', {
    project_id: projectId,
    ref,
  });
  return data as ProjectGraph;
}

export interface BodyScope {
  tier: string;
  comp_id?: string | null;
  parent_id?: string | null;
  sub_id?: string | null;
  phase?: number | null;
}

export interface BodyResponse {
  ref: string;
  ref_head_sha: string;
  found: boolean;
  body_path: string | null;
  body_text: string;
}

/**
 * ``which`` selects which side of the substrate's two-body model the
 * server returns: ``"draft"`` (default) reads state.draft.body_path,
 * ``"review"`` reads state.review.body_path. Same response shape; the
 * source differs.
 */
export async function getBody(
  projectId: string,
  scope: BodyScope,
  ref = 'main',
  which: 'draft' | 'review' = 'draft',
): Promise<BodyResponse> {
  const { data } = await siegeApi.post('/get-body', {
    project_id: projectId,
    ref,
    ...scope,
    which,
  });
  return data as BodyResponse;
}

// ── State (full per-scope state file projection) ────────────────────

export type ScopeStatus = 'absent' | 'drafted' | 'reviewed' | 'approved';

export interface ScopeDraftBlock {
  body_path: string;
  body_sha256: string;
  generated_at: string;
  generator_metadata?: Record<string, unknown>;
  prior_review_text?: string;
}

export interface ScopeReviewBlock {
  body_path: string;
  body_sha256: string;
  reviewed_at: string;
  score: number | null;
  reviewer_metadata?: Record<string, unknown>;
}

export interface ScopeApprovalBlock {
  approved_at: string;
  approved_by: string;
}

export interface ScopeStateResponse {
  ref: string;
  ref_head_sha: string;
  found: boolean;
  /** Present iff ``found`` — the parsed state JSON. */
  schema_version?: number;
  scope?: BodyScope;
  status?: ScopeStatus;
  nonce?: string;
  is_foundation?: boolean;
  draft?: ScopeDraftBlock | null;
  review?: ScopeReviewBlock | null;
  approval?: ScopeApprovalBlock | null;
  edges?: Record<string, string[]>;
  meta?: Record<string, unknown>;
  drift?: Record<string, unknown>;
}

export async function getScopeState(
  projectId: string,
  scope: BodyScope,
  ref = 'main',
): Promise<ScopeStateResponse> {
  const { data } = await siegeApi.post('/get-state', {
    project_id: projectId,
    ref,
    ...scope,
  });
  return data as ScopeStateResponse;
}
