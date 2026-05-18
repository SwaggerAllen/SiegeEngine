import { useCallback, useEffect, useRef, useState } from 'react';
import { connectGitHub, fetchGitHubAuthorizeUrl, fetchGitHubStatus } from '../api/github';
import { describeApiError } from '../lib/describeApiError';

/**
 * Per-user "Connect GitHub" panel. Opens a popup to the OAuth
 * authorize URL, listens for the callback page's postMessage, and
 * exchanges the code with the backend.
 *
 * The flow lives across three files in lockstep:
 *
 *   - backend/github/oauth.py — issues the authorize URL, exchanges
 *     the code, persists the credential.
 *   - frontend/src/pages/GitHubCallbackPage.tsx — runs at the OAuth
 *     redirect target, postMessages the code+state to opener, closes.
 *   - this file — opens the popup, receives the postMessage, calls
 *     /github/connect, refreshes status.
 *
 * The dashboard backend uses the stored credential for any server-
 * side git operations (pushing branches, opening PRs). Skills run in
 * Claude Code and use the user's local git creds; this panel doesn't
 * affect those.
 */
export default function GitHubConnectPanel() {
  const [status, setStatus] = useState<'loading' | 'idle' | 'connecting' | 'error'>('loading');
  const [connected, setConnected] = useState(false);
  const [username, setUsername] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const popupRef = useRef<Window | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await fetchGitHubStatus();
      setConnected(data.connected);
      setUsername(data.github_username ?? null);
      setStatus('idle');
    } catch (err: unknown) {
      setError(describeApiError(err, 'GitHub connection failed'));
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Listen for the callback popup's postMessage. The callback page
  // closes itself after posting, so we don't have to.
  useEffect(() => {
    const onMessage = async (event: MessageEvent) => {
      // Same-origin only — the OAuth callback page runs at our own
      // origin, so any cross-origin message is an attempt to spoof.
      if (event.origin !== window.location.origin) return;
      const data = event.data as { type?: string; code?: string; state?: string } | null;
      if (!data || data.type !== 'github-oauth' || !data.code || !data.state) return;
      setStatus('connecting');
      setError(null);
      try {
        const next = await connectGitHub(data.code, data.state);
        setConnected(next.connected);
        setUsername(next.github_username ?? null);
        setStatus('idle');
      } catch (err: unknown) {
        setError(describeApiError(err, 'GitHub connection failed'));
        setStatus('error');
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  const onConnect = async () => {
    setError(null);
    setStatus('connecting');
    try {
      const url = await fetchGitHubAuthorizeUrl();
      // Popup geometry: small but tall enough for GitHub's authorize
      // page without internal scroll on a 1080p display.
      const popup = window.open(
        url,
        'siege-github-oauth',
        'width=600,height=720,resizable=yes,scrollbars=yes',
      );
      if (!popup) {
        throw new Error(
          'Popup blocked. Allow popups for this site and try again.',
        );
      }
      popupRef.current = popup;
    } catch (err: unknown) {
      setError(describeApiError(err, 'GitHub connection failed'));
      setStatus('error');
    }
  };

  return (
    <section className="mb-6 rounded border border-gray-800 bg-gray-900 p-4">
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="text-sm font-semibold text-gray-200">GitHub connection</h2>
        {status === 'loading' && <span className="text-xs text-gray-500">loading…</span>}
      </div>

      {status === 'error' && error && (
        <div className="mb-3 rounded border border-red-800 bg-red-950/40 p-2 text-xs text-red-200">
          {error}
        </div>
      )}

      {!connected && status !== 'loading' && (
        <>
          <p className="mb-3 text-sm text-gray-400">
            Connect your GitHub account so the dashboard can push branches and open pull requests
            on your behalf. Uses the GitHub OAuth app configured on the server; you'll be redirected
            to GitHub to authorize.
          </p>
          <button
            type="button"
            onClick={onConnect}
            disabled={status === 'connecting'}
            className="px-3 py-1.5 text-sm rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white"
          >
            {status === 'connecting' ? 'Connecting…' : 'Connect GitHub'}
          </button>
        </>
      )}

      {connected && (
        <p className="text-sm text-gray-300">
          Connected as <strong className="text-gray-100">@{username ?? 'unknown'}</strong>.{' '}
          <button
            type="button"
            onClick={onConnect}
            className="text-xs text-blue-400 hover:text-blue-300 underline"
          >
            re-authorize
          </button>
        </p>
      )}
    </section>
  );
}
