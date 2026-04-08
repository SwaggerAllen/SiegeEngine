import { useState, useEffect, useMemo } from 'react';
import { getArtifactDiff, type ArtifactDiff } from '../../api/pipeline';

interface DiffViewProps {
  projectId: string;
  artifactId: string;
  artifactVersion: number;
  /** When set, diff the current version against this specific commit SHA. */
  compareToSha?: string | null;
}

interface ParsedLine {
  line: string;
  type: 'added' | 'removed' | 'context' | 'header';
}

interface Hunk {
  header: string;
  lines: ParsedLine[];
  addCount: number;
  removeCount: number;
}

function parseDiffIntoHunks(diff: string): { preambleLines: ParsedLine[]; hunks: Hunk[] } {
  const lines = diff.split('\n');
  const preambleLines: ParsedLine[] = [];
  const hunks: Hunk[] = [];
  let currentHunk: Hunk | null = null;

  for (const line of lines) {
    if (line.startsWith('@@')) {
      // Start a new hunk
      currentHunk = { header: line, lines: [], addCount: 0, removeCount: 0 };
      hunks.push(currentHunk);
    } else if (currentHunk) {
      let type: ParsedLine['type'] = 'context';
      if (line.startsWith('+')) {
        type = 'added';
        currentHunk.addCount++;
      } else if (line.startsWith('-')) {
        type = 'removed';
        currentHunk.removeCount++;
      }
      currentHunk.lines.push({ line, type });
    } else {
      // Lines before any hunk header (e.g., file headers)
      preambleLines.push({ line, type: 'context' });
    }
  }

  return { preambleLines, hunks };
}

const lineClass: Record<ParsedLine['type'], string> = {
  added: 'bg-green-900/30 text-green-300',
  removed: 'bg-red-900/30 text-red-300',
  header: 'text-blue-400 mt-2',
  context: 'text-gray-300',
};

export default function DiffView({ projectId, artifactId, artifactVersion, compareToSha }: DiffViewProps) {
  const [diff, setDiff] = useState<ArtifactDiff | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [collapsedHunks, setCollapsedHunks] = useState<Set<number>>(() => new Set());

  useEffect(() => {
    if (artifactVersion <= 1 && !compareToSha) {
      setLoading(false);
      setError('No previous version to compare against.');
      return;
    }

    setLoading(true);
    setError(null);
    setCollapsedHunks(new Set());
    getArtifactDiff(projectId, artifactId, compareToSha || undefined)
      .then(setDiff)
      .catch((e) => setError(e?.response?.data?.detail || 'Failed to load diff'))
      .finally(() => setLoading(false));
  }, [projectId, artifactId, artifactVersion, compareToSha]);

  const parsed = useMemo(() => (diff?.diff ? parseDiffIntoHunks(diff.diff) : null), [diff]);

  const toggleHunk = (idx: number) => {
    setCollapsedHunks((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  if (loading) {
    return <div className="p-4 text-gray-400">Loading diff...</div>;
  }

  if (error) {
    return <div className="p-4 text-gray-500">{error}</div>;
  }

  if (!diff || !diff.diff || !parsed) {
    return <div className="p-4 text-gray-500">No changes detected.</div>;
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-2 text-sm text-gray-400 border-b border-gray-700 flex-shrink-0">
        v{diff.from_version} → v{diff.to_version}
      </div>
      <div className="flex-1 overflow-auto">
        <div className="text-sm font-mono p-4 pb-64 leading-relaxed whitespace-pre-wrap break-words" style={{ overflowWrap: 'anywhere' }}>
          {/* Preamble lines (file headers, etc.) */}
          {parsed.preambleLines.map((pl, i) => (
            <div key={`pre-${i}`} className={lineClass[pl.type]}>{pl.line}</div>
          ))}

          {/* Hunks */}
          {parsed.hunks.map((hunk, idx) => {
            const isCollapsed = collapsedHunks.has(idx);
            return (
              <div key={idx}>
                <div
                  onClick={() => toggleHunk(idx)}
                  className="text-blue-400 mt-2 cursor-pointer select-none flex items-center gap-2 group hover:text-blue-300"
                >
                  <span
                    className="text-gray-500 group-hover:text-gray-300 transition-transform duration-150 text-[10px] inline-block shrink-0"
                    style={{ transform: isCollapsed ? undefined : 'rotate(90deg)' }}
                  >▶</span>
                  <span className="flex-1">{hunk.header}</span>
                  <span className="text-xs text-gray-500 shrink-0">
                    {hunk.addCount > 0 && <span className="text-green-500">+{hunk.addCount}</span>}
                    {hunk.addCount > 0 && hunk.removeCount > 0 && ' / '}
                    {hunk.removeCount > 0 && <span className="text-red-500">-{hunk.removeCount}</span>}
                  </span>
                </div>
                {!isCollapsed && hunk.lines.map((pl, li) => (
                  <div key={li} className={lineClass[pl.type]}>{pl.line}</div>
                ))}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
