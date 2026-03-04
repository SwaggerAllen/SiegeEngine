import { useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import type { Artifact } from '../../types/project';

export function ArtifactEditor({ artifact }: { artifact: Artifact }) {
  const { updateArtifact } = useProjectStore();
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(artifact.content || '');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateArtifact(artifact.id, content);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700">
        <div>
          <span className="text-sm font-medium text-white">{artifact.name}</span>
          <span className="text-xs text-gray-400 ml-2">v{artifact.version}</span>
          <span
            className={`text-xs ml-2 px-1.5 py-0.5 rounded ${
              artifact.status === 'approved'
                ? 'bg-green-900 text-green-300'
                : artifact.status === 'stale'
                ? 'bg-orange-900 text-orange-300'
                : artifact.status === 'awaiting_review'
                ? 'bg-yellow-900 text-yellow-300'
                : 'bg-gray-700 text-gray-300'
            }`}
          >
            {artifact.status}
          </span>
        </div>
        <div className="flex gap-2">
          {editing ? (
            <>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-2 py-1 bg-green-600 hover:bg-green-700 text-white text-xs rounded disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button
                onClick={() => {
                  setContent(artifact.content || '');
                  setEditing(false);
                }}
                className="px-2 py-1 bg-gray-600 hover:bg-gray-500 text-white text-xs rounded"
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              onClick={() => setEditing(true)}
              className="px-2 py-1 bg-gray-600 hover:bg-gray-500 text-white text-xs rounded"
            >
              Edit
            </button>
          )}
        </div>
      </div>

      {editing ? (
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          className="flex-1 w-full p-3 bg-gray-900 text-white font-mono text-sm resize-none focus:outline-none"
        />
      ) : (
        <pre className="flex-1 p-3 overflow-auto text-sm text-gray-200 whitespace-pre-wrap font-mono">
          {artifact.content || 'No content'}
        </pre>
      )}
    </div>
  );
}
