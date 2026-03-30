import { useState, useEffect } from 'react';
import { getArtifactDiff, type ArtifactDiff } from '../../api/pipeline';

interface DiffViewProps {
  projectId: string;
  artifactId: string;
  artifactVersion: number;
  /** When set, diff the current version against this specific commit SHA. */
  compareToSha?: string | null;
}

function parseDiff(diff: string) {
  const lines = diff.split('\n');
  return lines.map((line, i) => {
    let type: 'added' | 'removed' | 'context' | 'header' = 'context';
    if (line.startsWith('@@')) type = 'header';
    else if (line.startsWith('+')) type = 'added';
    else if (line.startsWith('-')) type = 'removed';
    return { line, type, key: i };
  });
}

export default function DiffView({ projectId, artifactId, artifactVersion, compareToSha }: DiffViewProps) {
  const [diff, setDiff] = useState<ArtifactDiff | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (artifactVersion <= 1 && !compareToSha) {
      setLoading(false);
      setError('No previous version to compare against.');
      return;
    }

    setLoading(true);
    setError(null);
    getArtifactDiff(projectId, artifactId, compareToSha || undefined)
      .then(setDiff)
      .catch((e) => setError(e?.response?.data?.detail || 'Failed to load diff'))
      .finally(() => setLoading(false));
  }, [projectId, artifactId, artifactVersion, compareToSha]);

  if (loading) {
    return <div className="p-4 text-gray-400">Loading diff...</div>;
  }

  if (error) {
    return <div className="p-4 text-gray-500">{error}</div>;
  }

  if (!diff || !diff.diff) {
    return <div className="p-4 text-gray-500">No changes detected.</div>;
  }

  const parsed = parseDiff(diff.diff);

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-2 text-sm text-gray-400 border-b border-gray-700 flex-shrink-0">
        v{diff.from_version} → v{diff.to_version}
      </div>
      <div className="flex-1 overflow-auto">
        <div className="text-sm font-mono p-4 leading-relaxed whitespace-pre-wrap break-words" style={{ overflowWrap: 'anywhere' }}>
          {parsed.map(({ line, type, key }) => (
            <div
              key={key}
              className={
                type === 'added'
                  ? 'bg-green-900/30 text-green-300'
                  : type === 'removed'
                  ? 'bg-red-900/30 text-red-300'
                  : type === 'header'
                  ? 'text-blue-400 mt-2'
                  : 'text-gray-300'
              }
            >
              {line}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
