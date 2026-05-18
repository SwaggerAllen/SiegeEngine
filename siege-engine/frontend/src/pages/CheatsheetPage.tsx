import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Markdown from 'react-markdown';
import DevTokenPanel from '../components/DevTokenPanel';

/**
 * Renders the SiegeEngine workflow + slash command cheat sheet.
 *
 * The markdown source lives in the repo at `docs/cheatsheet.md` and
 * is served by `siege_mcp.server` at `/siege_mcp/api/cheatsheet`.
 * Edit the markdown file when commands or skills change — the page
 * picks up the next response on its next render.
 *
 * Deliberately UNAUTHENTICATED. The cheat sheet is documentation,
 * not user data; gating it would force a login flow before someone
 * can read how to use the system.
 */
export default function CheatsheetPage() {
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/siege_mcp/api/cheatsheet')
      .then((r) => {
        if (!r.ok) throw new Error(`fetch failed: ${r.status}`);
        return r.json();
      })
      .then((data: { markdown: string }) => {
        if (!cancelled) setMarkdown(data.markdown);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold">SiegeEngine cheat sheet</h1>
        <Link
          to="/projects"
          className="text-sm text-blue-400 hover:text-blue-300"
        >
          ← back to projects
        </Link>
      </header>
      <main className="max-w-4xl mx-auto px-6 py-8">
        <DevTokenPanel />
        {error && (
          <div className="rounded border border-red-800 bg-red-950/40 p-4 text-sm">
            Failed to load: {error}
          </div>
        )}
        {!error && markdown === null && (
          <div className="text-sm text-gray-400">Loading…</div>
        )}
        {markdown && (
          <article className="prose prose-invert prose-sm max-w-none">
            <Markdown>{markdown}</Markdown>
          </article>
        )}
      </main>
    </div>
  );
}
