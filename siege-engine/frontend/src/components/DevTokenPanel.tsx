import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

/**
 * Show the logged-in user's JWT in a copy-paste-ready `export
 * SIEGE_TOKEN=…` form, with the expiry date alongside. Used on the
 * cheat sheet page so the bootstrap script's "export SIEGE_TOKEN=…"
 * step is one click away from the docs that describe it.
 *
 * Falls back to a "log in to get your token" prompt when the user
 * isn't authenticated — the cheat sheet page itself is open so this
 * panel is the only auth-gated surface on the route.
 */
export default function DevTokenPanel() {
  const token = useAuthStore((s) => s.token);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const username = useAuthStore((s) => s.user?.username);
  const [copied, setCopied] = useState<'token' | 'export' | null>(null);

  const expiry = parseExpiry(token);

  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(null), 1600);
    return () => window.clearTimeout(t);
  }, [copied]);

  if (!isAuthenticated || !token) {
    return (
      <div className="mb-8 rounded border border-gray-800 bg-gray-900 p-4 text-sm">
        <strong className="text-gray-200">Need a token?</strong>{' '}
        <Link to="/login" className="text-blue-400 hover:text-blue-300">
          Log in
        </Link>{' '}
        and your JWT will appear here. Then paste the{' '}
        <code className="px-1 bg-gray-800 rounded">export SIEGE_TOKEN=…</code>{' '}
        line into your shell.
      </div>
    );
  }

  const exportLine = `export SIEGE_TOKEN=${token}`;
  const copy = async (text: string, key: 'token' | 'export') => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
    } catch {
      // navigator.clipboard can fail under non-secure contexts; surface a
      // best-effort fallback so the user can still select + copy manually.
      window.prompt('Copy your token:', text);
    }
  };

  return (
    <div className="mb-8 rounded border border-gray-800 bg-gray-900 p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-200">
          Your dev token{username ? ` — ${username}` : ''}
        </h2>
        {expiry && (
          <span className="text-xs text-gray-400">
            expires {formatDate(expiry)}
            {expiryFromNow(expiry) && (
              <span className="ml-2 text-gray-500">({expiryFromNow(expiry)})</span>
            )}
          </span>
        )}
      </div>

      <div className="space-y-3 text-sm">
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs uppercase tracking-wide text-gray-500">Shell export</span>
            <button
              type="button"
              onClick={() => copy(exportLine, 'export')}
              className="text-xs px-2 py-0.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-200"
            >
              {copied === 'export' ? 'copied ✓' : 'copy'}
            </button>
          </div>
          <pre className="overflow-x-auto p-2 bg-gray-950 rounded text-xs text-gray-300">
            {`export SIEGE_TOKEN=${midElide(token, 40, 20)}`}
          </pre>
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs uppercase tracking-wide text-gray-500">Raw JWT</span>
            <button
              type="button"
              onClick={() => copy(token, 'token')}
              className="text-xs px-2 py-0.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-200"
            >
              {copied === 'token' ? 'copied ✓' : 'copy'}
            </button>
          </div>
          <code className="block break-all p-2 bg-gray-950 rounded text-xs text-gray-400 font-mono">
            {midElide(token, 40, 20)}
          </code>
        </div>

        <p className="text-xs text-gray-500">
          Paste the shell export into <code className="px-1 bg-gray-800 rounded">~/.bashrc</code> /{' '}
          <code className="px-1 bg-gray-800 rounded">~/.zshrc</code> to persist across sessions.
          The token expires automatically — return here for a fresh one.
        </p>
      </div>
    </div>
  );
}

function parseExpiry(token: string | null): Date | null {
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length < 2) return null;
    const payload = JSON.parse(atob(parts[1]));
    if (typeof payload.exp !== 'number') return null;
    return new Date(payload.exp * 1000);
  } catch {
    return null;
  }
}

function formatDate(d: Date): string {
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function expiryFromNow(d: Date): string | null {
  const ms = d.getTime() - Date.now();
  if (ms <= 0) return 'expired';
  const days = Math.floor(ms / (24 * 60 * 60 * 1000));
  if (days >= 1) return `in ${days}d`;
  const hours = Math.floor(ms / (60 * 60 * 1000));
  if (hours >= 1) return `in ${hours}h`;
  const minutes = Math.floor(ms / (60 * 1000));
  return `in ${minutes}m`;
}

/**
 * Show the first `head` chars + ellipsis + the last `tail` chars.
 * For JWTs, this lets the user eyeball the head (recognizable
 * structure) and the tail (last few sig chars) without bleeding the
 * whole signature across the page.
 */
function midElide(s: string, head: number, tail: number): string {
  if (s.length <= head + tail + 1) return s;
  return `${s.slice(0, head)}…${s.slice(s.length - tail)}`;
}
