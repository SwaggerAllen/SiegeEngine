# SiegeEngine frontend

React + Vite + TypeScript + Zustand + Tailwind dashboard for the
SiegeEngine project. Reads project state from the MCP server
(`siege/` in the parent directory) and renders structure,
review summaries, and per-tier scores.

For project-level docs, install instructions, and the full
configuration reference see [../README.md](../README.md).

## Dev

```bash
npm install
npm run dev        # localhost:5173, proxies to backend on :8000
```

Backend must be running locally (`uvicorn backend.main:app
--reload --port 8000` from the parent `siege-engine/` directory).

## Verify before committing

```bash
npx tsc -b --noEmit --force
npx vitest run
npm run lint
npx vite build
```

`tsc -b --force` defeats stale buildinfo caches; vitest covers the
component + hook layer.

## Patterns to know

- **Zustand stores** use `createSafeStore` (not bare `create()`);
  middleware catches async action errors and logs to
  `errorLogStore`. See `src/store/createSafeStore.ts`.
- **Selectors are required** on every store read:
  `useStore((s) => s.field)`, never bare destructuring.
- **Safe hook wrappers** in `src/hooks/useSafe.ts` —
  `useSafeEffect` / `useSafeMemo` / `useSafeCallback` catch errors
  that React's error boundaries miss.
- The cheat sheet markdown lives at `src/content/cheatsheet.md` and
  is bundled into the build via Vite's `?raw` import. Edit there
  when commands or skills change.

## License

AGPL-3.0-or-later, same as the rest of the repo. See
[../../LICENSE](../../LICENSE).
