import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../api/client';

/**
 * Branch selector + page-level ref context.
 *
 * The dashboard now reads against a chosen git ref (branch or sha)
 * served by the future MCP HTTP transport. The selected ref is
 * shared with every data hook on ``ProjectWorkspacePage`` via the
 * ``RefContext`` exported here so per-tier hooks can include it
 * as a query param when they're repointed at the new endpoints.
 *
 * Persistence: ``localStorage["siege:projectworkspace:ref:<projectId>"]``.
 * Default: ``main``.
 *
 * FUTURE: MCP server endpoint GET /api/projects/:id/refs returning
 * ``{refs: [{name, head_sha, head_subject}]}``;
 * see docs/migration/mcp-surface.md.
 */

const REF_STORAGE_KEY_PREFIX = 'siege:projectworkspace:ref:';
const DEFAULT_REF = 'main';

export interface RefInfo {
  name: string;
  head_sha: string;
  head_subject: string;
}

interface RefsResponse {
  refs: RefInfo[];
}

interface RefContextValue {
  ref: string;
  setRef: (next: string) => void;
}

const RefContext = createContext<RefContextValue | null>(null);

export function useSelectedRef(): string {
  // Reads outside the provider get the default. Per-tier hooks
  // can pull the live value where they need it.
  const ctx = useContext(RefContext);
  return ctx?.ref ?? DEFAULT_REF;
}

export function useSetSelectedRef(): (next: string) => void {
  const ctx = useContext(RefContext);
  if (!ctx) {
    throw new Error('useSetSelectedRef must be used inside <RefProvider>');
  }
  return ctx.setRef;
}

function storageKey(projectId: string): string {
  return `${REF_STORAGE_KEY_PREFIX}${projectId}`;
}

function readPersistedRef(projectId: string): string {
  try {
    return localStorage.getItem(storageKey(projectId)) || DEFAULT_REF;
  } catch {
    return DEFAULT_REF;
  }
}

export function RefProvider({
  projectId,
  children,
}: {
  projectId: string;
  children: React.ReactNode;
}) {
  const [ref, setRefState] = useState<string>(() => readPersistedRef(projectId));

  // Re-seed when the project changes — different project, different key.
  useEffect(() => {
    setRefState(readPersistedRef(projectId));
  }, [projectId]);

  const setRef = useCallback(
    (next: string) => {
      setRefState(next);
      try {
        localStorage.setItem(storageKey(projectId), next);
      } catch {
        // ignore quota / unavailable storage; in-memory state is the source of truth
      }
    },
    [projectId],
  );

  const value = useMemo<RefContextValue>(() => ({ ref, setRef }), [ref, setRef]);

  return <RefContext.Provider value={value}>{children}</RefContext.Provider>;
}

/**
 * Fetch the project's available refs.
 *
 * FUTURE: MCP server endpoint GET /api/projects/:id/refs
 * served by the new MCP HTTP transport. Until the backend ships,
 * the fetch falls back to a single synthetic ``main`` entry so
 * the selector still renders and the user can navigate.
 */
export function useRefs(projectId: string) {
  return useQuery<RefsResponse>({
    queryKey: ['refs', projectId],
    queryFn: async () => {
      try {
        const r = await api.get(`/projects/${projectId}/refs`);
        const data = r.data as Partial<RefsResponse>;
        if (Array.isArray(data?.refs)) {
          return { refs: data.refs };
        }
      } catch {
        // Endpoint not yet served. Fall through to stub.
      }
      return {
        refs: [
          {
            name: DEFAULT_REF,
            head_sha: '',
            head_subject: '',
          },
        ],
      };
    },
    staleTime: 60_000,
    enabled: !!projectId,
  });
}

interface BranchSelectorProps {
  projectId: string;
}

/**
 * Compact <select> dropdown for the project's available refs.
 * Lives in the workspace header; selection persists per-project
 * to localStorage so the user lands on the same ref on reload.
 */
export function BranchSelector({ projectId }: BranchSelectorProps) {
  const ctx = useContext(RefContext);
  const { data } = useRefs(projectId);
  const refs = data?.refs ?? [];

  if (!ctx) return null;

  const options = refs.length
    ? refs
    : [{ name: ctx.ref || DEFAULT_REF, head_sha: '', head_subject: '' }];

  return (
    <label className="shrink-0 inline-flex items-center gap-1 text-xs text-gray-400">
      <span className="sr-only">Git ref</span>
      <select
        aria-label="Git ref"
        value={ctx.ref}
        onChange={(e) => ctx.setRef(e.target.value)}
        className="bg-gray-900 border border-gray-700 rounded px-1.5 py-0.5 text-xs text-gray-200 hover:border-gray-500 focus:outline-none focus:border-gray-400 max-w-[10rem] truncate"
        title="Switch git ref"
      >
        {options.map((r) => (
          <option key={r.name} value={r.name}>
            {r.name}
          </option>
        ))}
      </select>
    </label>
  );
}
