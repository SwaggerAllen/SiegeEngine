import { useCallback, useEffect, useState } from 'react';

interface Props {
  projectId: string;
  getPromptPreview: (feedback: string) => Promise<{
    system_prompt: string;
    user_prompt: string;
  }>;
}

export function PromptPreviewPanel({ projectId, getPromptPreview }: Props) {
  const [preview, setPreview] = useState<{
    system_prompt: string;
    user_prompt: string;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState('');

  const fetchPreview = useCallback(() => {
    setLoading(true);
    setError(null);
    getPromptPreview(feedback.trim())
      .then(setPreview)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [getPromptPreview, feedback]);

  useEffect(() => {
    fetchPreview();
  }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="p-4 space-y-4 max-w-4xl mx-auto">
      <div className="flex items-end gap-3">
        <div className="flex-1">
          <label className="block text-xs text-gray-400 mb-1">
            Preview with feedback (optional)
          </label>
          <input
            type="text"
            className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm"
            placeholder="Type feedback to see how it appears in the prompt…"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
          />
        </div>
        <button
          type="button"
          onClick={fetchPreview}
          disabled={loading}
          className="px-4 py-1.5 text-sm rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40 shrink-0"
        >
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-400">Failed to load preview: {error}</div>
      )}

      {preview && (
        <div className="space-y-6">
          <section>
            <h3 className="text-xs text-gray-500 font-semibold uppercase tracking-wide mb-2">
              System Prompt
            </h3>
            <pre className="bg-gray-900 border border-gray-700 rounded p-3 text-xs text-gray-300 whitespace-pre-wrap overflow-x-auto max-h-[50vh] overflow-y-auto">
              {preview.system_prompt}
            </pre>
          </section>
          <section>
            <h3 className="text-xs text-gray-500 font-semibold uppercase tracking-wide mb-2">
              User Prompt
            </h3>
            <pre className="bg-gray-900 border border-gray-700 rounded p-3 text-xs text-gray-300 whitespace-pre-wrap overflow-x-auto max-h-[50vh] overflow-y-auto">
              {preview.user_prompt}
            </pre>
          </section>
        </div>
      )}
    </div>
  );
}
