import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import api from '../api/client';
import { fetchGitHubStatus, type GitHubStatus } from '../api/github';
import { useAuthStore } from '../store/authStore';

interface McpAuthDebug {
  user_id_from_context: string | null;
  user_id_in_claims: string | null;
  context_matches_claims: boolean;
  project_id_queried: string | null;
  project_remote_url: string | null;
  has_token: boolean;
  token_prefix: string | null;
  token_length: number;
}

/**
 * Live diagnostic panel for the auth wiring the MCP server depends on:
 *
 *   1. **JWT identity** — decodes the stored token to show the `sub`
 *      claim (the user id the MCP server sees on every request).
 *   2. **Dashboard identity** — calls `/api/auth/me` to confirm the
 *      same JWT resolves to a real user server-side. Flags a
 *      mismatch when the JWT's `sub` and the server's view diverge.
 *   3. **GitHub connection** — calls `/api/github/status` to confirm
 *      a `GitHubCredential` row exists for this user. Without one,
 *      the MCP server can't authenticate private-repo clones.
 *
 * Everything's auth-gated (panel hides when not logged in). Refresh
 * button re-runs the lookups on demand so users can verify a fresh
 * re-authorize landed without reloading the page.
 */
export default function AuthDebugPanel() {
  const token = useAuthStore((s) => s.token);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const [me, setMe] = useState<{ id: string; username: string; role?: string } | null>(null);
  const [meError, setMeError] = useState<string | null>(null);
  const [gh, setGh] = useState<GitHubStatus | null>(null);
  const [ghError, setGhError] = useState<string | null>(null);
  const [mcp, setMcp] = useState<McpAuthDebug | null>(null);
  const [mcpError, setMcpError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Pick up the project_id from the URL if we're on a project-scoped
  // route; cheatsheet has no project context so the MCP lookup runs
  // with a dummy id (still validates the user lookup, just can't tell
  // us the per-project remote_url).
  const { id: projectIdFromRoute } = useParams<{ id?: string }>();
  const projectId = projectIdFromRoute ?? null;

  const refresh = useCallback(async () => {
    if (!isAuthenticated) return;
    setBusy(true);
    setMeError(null);
    setGhError(null);
    setMcpError(null);
    await Promise.all([
      (async () => {
        try {
          const r = await api.get('/auth/me');
          setMe(r.data);
        } catch (err: unknown) {
          const e = err as { response?: { status?: number; data?: { detail?: string } } };
          setMeError(
            e?.response?.data?.detail
              ? `${e.response.status}: ${e.response.data.detail}`
              : `${e?.response?.status ?? 'network error'}`,
          );
        }
      })(),
      (async () => {
        try {
          setGh(await fetchGitHubStatus());
        } catch (err: unknown) {
          const e = err as { response?: { status?: number; data?: { detail?: string } } };
          setGhError(
            e?.response?.data?.detail
              ? `${e.response.status}: ${e.response.data.detail}`
              : `${e?.response?.status ?? 'network error'}`,
          );
        }
      })(),
      (async () => {
        try {
          // The MCP server lives at /siege_mcp on the same origin;
          // hit its debug endpoint directly (not via the /api axios
          // base) and pass the same bearer token.
          const url = projectId
            ? `/siege_mcp/api/debug/mcp-auth?project_id=${encodeURIComponent(projectId)}`
            : '/siege_mcp/api/debug/mcp-auth';
          const r = await fetch(url, {
            headers: { Authorization: `Bearer ${token ?? ''}` },
          });
          if (!r.ok) throw new Error(`${r.status}`);
          setMcp((await r.json()) as McpAuthDebug);
        } catch (err: unknown) {
          setMcpError(err instanceof Error ? err.message : 'unknown');
        }
      })(),
    ]);
    setBusy(false);
  }, [isAuthenticated, projectId, token]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!isAuthenticated || !token) return null;

  const jwt = parseJwt(token);
  const sub = jwt?.sub ?? null;
  const subMismatch = me && sub && me.id !== sub;

  return (
    <section className="mb-8 rounded border border-gray-800 bg-gray-900 p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-200">Auth diagnostic</h2>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={busy}
          className="text-xs px-2 py-0.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-200 disabled:opacity-50"
        >
          {busy ? 'checking…' : 'refresh'}
        </button>
      </div>

      <div className="space-y-3 text-sm">
        <Row
          label="JWT sub (MCP server sees this)"
          value={sub ?? '(missing — bad token shape?)'}
          tone={sub ? 'ok' : 'warn'}
        />
        <Row
          label="JWT username"
          value={jwt?.username ?? '(none)'}
          tone="ok"
        />

        <Row
          label="Dashboard user (/auth/me)"
          value={
            meError
              ? `error: ${meError}`
              : me
              ? `${me.username} (${me.id})${me.role ? ` · role=${me.role}` : ''}`
              : 'loading…'
          }
          tone={meError ? 'err' : me ? 'ok' : 'idle'}
        />

        {subMismatch && (
          <div className="rounded border border-amber-700 bg-amber-950/40 p-2 text-xs text-amber-200">
            <strong>Identity mismatch:</strong> the JWT's <code>sub</code> ({sub}) doesn't match
            the dashboard's view of you ({me?.id}). Likely two accounts. Log out, log back in as
            the right user, copy the new JWT from this page into <code>SIEGE_TOKEN</code>.
          </div>
        )}

        <Row
          label="GitHub connected"
          value={
            ghError
              ? `error: ${ghError}`
              : gh
              ? gh.connected
                ? `yes — @${gh.github_username ?? '(unknown)'}`
                : 'no — Connect GitHub on Project Settings'
              : 'loading…'
          }
          tone={ghError ? 'err' : gh ? (gh.connected ? 'ok' : 'warn') : 'idle'}
        />

        {gh && !gh.connected && !ghError && (
          <div className="rounded border border-amber-700 bg-amber-950/40 p-2 text-xs text-amber-200">
            No <code>GitHubCredential</code> row for this user. Private-repo clones from MCP will
            fail with "Clone of … requires authentication" until you complete the OAuth flow on a
            project's Settings page.
          </div>
        )}

        <Row
          label={`MCP token lookup${projectId ? ` (project: ${projectId})` : ''}`}
          value={
            mcpError
              ? `error: ${mcpError}`
              : mcp
              ? mcp.has_token
                ? `${mcp.token_prefix} (${mcp.token_length} chars)` +
                  (mcp.project_remote_url ? ` · remote: ${mcp.project_remote_url}` : '')
                : 'NO TOKEN — MCP server sees user but no GitHubCredential row'
              : 'loading…'
          }
          tone={mcpError ? 'err' : mcp ? (mcp.has_token ? 'ok' : 'warn') : 'idle'}
        />

        {mcp && !mcp.has_token && gh?.connected && (
          <div className="rounded border border-red-800 bg-red-950/40 p-2 text-xs text-red-200">
            <strong>Inconsistency:</strong> the dashboard says you're connected to GitHub, but the
            MCP server's lookup can't find a token for the same user. Either the request context
            isn't propagating the user id correctly, or the dashboard's view is stale (a deploy
            mid-flight, two server instances disagreeing, etc.). Try the refresh button; if it
            persists, file an issue with this panel's contents.
          </div>
        )}

        {mcp && mcp.context_matches_claims === false && (
          <div className="rounded border border-red-800 bg-red-950/40 p-2 text-xs text-red-200">
            <strong>Context propagation bug:</strong> the JWT claims say{' '}
            <code>{mcp.user_id_in_claims}</code> but the ContextVar inside the tool handler holds{' '}
            <code>{mcp.user_id_from_context ?? '(none)'}</code>. siege_mcp's user_id_context
            handling is broken.
          </div>
        )}
      </div>
    </section>
  );
}

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: 'ok' | 'warn' | 'err' | 'idle';
}) {
  const toneClass =
    tone === 'ok'
      ? 'text-green-300'
      : tone === 'warn'
      ? 'text-amber-300'
      : tone === 'err'
      ? 'text-red-300'
      : 'text-gray-400';
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs uppercase tracking-wide text-gray-500">{label}</span>
      <code className={`break-all font-mono text-xs ${toneClass}`}>{value}</code>
    </div>
  );
}

/**
 * Decode a JWT's payload segment without verifying the signature.
 * The dashboard already trusts the token (it was issued by the same
 * server it's talking to); this is just to read the claims for
 * display.
 */
function parseJwt(token: string): { sub?: string; username?: string; exp?: number } | null {
  try {
    const parts = token.split('.');
    if (parts.length < 2) return null;
    return JSON.parse(atob(parts[1]));
  } catch {
    return null;
  }
}
