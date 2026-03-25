import { useState, useEffect } from 'react';
import { getPromptPreview } from '../../api/pipeline';
import { PromptPreviewPanel } from './ArtifactEditor';
import type { PromptPreview } from '../../api/pipeline';

export function ArtifactPromptDebugView({ projectId, artifactId }: { projectId: string; artifactId: string }) {
  const [preview, setPreview] = useState<PromptPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setPreview(null);
    setError(null);
    getPromptPreview(projectId, artifactId)
      .then(setPreview)
      .catch((err: unknown) => setError((err as Error)?.message || 'Failed to load prompt preview'))
      .finally(() => setLoading(false));
  }, [projectId, artifactId]);

  if (loading) return <div className="p-4 text-sm text-gray-400">Loading prompt preview...</div>;
  if (error) return <div className="p-4 text-sm text-red-400">{error}</div>;
  if (!preview) return <div className="p-4 text-sm text-gray-500">No prompt preview available.</div>;

  return (
    <div className="h-full overflow-auto p-3">
      <PromptPreviewPanel preview={preview} />
    </div>
  );
}
