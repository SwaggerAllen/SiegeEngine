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
