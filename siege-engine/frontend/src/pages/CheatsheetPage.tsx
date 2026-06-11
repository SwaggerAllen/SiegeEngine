import { Link } from 'react-router-dom';
import Markdown from 'react-markdown';
import DevTokenPanel from '../components/DevTokenPanel';
// Vite's `?raw` import bundles the markdown source as a string at
// build time. The file lives under frontend/src/content/ so it's
// inside the frontend tree (no cross-package path tricks); edits ship
// in the same commit as any other frontend change, and the served
// page is whatever the build pinned. No runtime fetch, no server
// endpoint, no JSON envelope.
import cheatsheetMarkdown from '../content/cheatsheet.md?raw';

/**
 * Renders the SiegeEngine workflow + slash command cheat sheet.
 *
 * Source: `frontend/src/content/cheatsheet.md`. Edit there when
 * commands or skills change — CLAUDE.md flags the file as
 * load-bearing.
 *
 * Deliberately UNAUTHENTICATED at the route level. The DevTokenPanel
 * is auth-aware on its own: shows the JWT export when logged in,
 * shows a "log in" prompt when not.
 */
export default function CheatsheetPage() {
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
        <article className="prose prose-invert prose-sm max-w-none">
          <Markdown>{cheatsheetMarkdown}</Markdown>
        </article>
      </main>
    </div>
  );
}
