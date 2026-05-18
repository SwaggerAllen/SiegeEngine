import api from './client';

/**
 * Per-user GitHub OAuth client. The dashboard backend stores one
 * `GitHubCredential` row per user; this module is the thin wrapper
 * around its three endpoints.
 *
 * Flow:
 *   1. status() → connected? username?
 *   2. authorize() → { authorize_url } that the popup opens
 *   3. User authorizes on GitHub, popup lands on /github/callback,
 *      callback postMessages { type: 'github-oauth', code, state }
 *      back to the opener.
 *   4. Opener calls connect({ code, state }) → token exchange,
 *      credential persisted server-side.
 *
 * See `backend/github/oauth.py` for the server side.
 */

export interface GitHubStatus {
  connected: boolean;
  github_username?: string | null;
}

export async function fetchGitHubStatus(): Promise<GitHubStatus> {
  const { data } = await api.get<GitHubStatus>('/github/status');
  return data;
}

export async function fetchGitHubAuthorizeUrl(): Promise<string> {
  const { data } = await api.get<{ authorize_url: string }>('/github/authorize');
  return data.authorize_url;
}

export async function connectGitHub(code: string, state: string): Promise<GitHubStatus> {
  const { data } = await api.post<{ status: string; github_username?: string }>(
    '/github/connect',
    { code, state },
  );
  return { connected: data.status === 'connected', github_username: data.github_username ?? null };
}
