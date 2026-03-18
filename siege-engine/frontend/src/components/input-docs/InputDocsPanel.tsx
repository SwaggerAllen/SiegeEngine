import { useEffect, useState } from 'react';
import {
  listInputDocs,
  createInputDoc,
  updateInputDoc,
  deleteInputDoc,
  propagateChanges,
  type InputDocument,
} from '../../api/inputDocs';
import { useAuthStore } from '../../store/authStore';

interface InputDocsPanelProps {
  projectId: string;
}

export default function InputDocsPanel({ projectId }: InputDocsPanelProps) {
  const { user } = useAuthStore();
  const isViewer = user?.role === 'viewer';

  const [docs, setDocs] = useState<InputDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editType, setEditType] = useState('reference');
  const [saving, setSaving] = useState(false);
  const [propagating, setPropagating] = useState(false);
  const [showNew, setShowNew] = useState(false);

  const fetchDocs = () => {
    listInputDocs(projectId).then(setDocs).finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchDocs();
  }, [projectId]);

  const selectedDoc = docs.find((d) => d.id === selectedId);

  const handleSelect = (doc: InputDocument) => {
    setSelectedId(doc.id);
    setEditName(doc.name);
    setEditContent(doc.content);
    setEditType(doc.doc_type);
    setShowNew(false);
  };

  const handleNew = () => {
    setSelectedId(null);
    setEditName('');
    setEditContent('');
    setEditType('reference');
    setShowNew(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      if (showNew) {
        const result = await createInputDoc(projectId, {
          name: editName,
          content: editContent,
          doc_type: editType,
        });
        setSelectedId(result.id);
        setShowNew(false);
      } else if (selectedId) {
        await updateInputDoc(projectId, selectedId, {
          name: editName,
          content: editContent,
          doc_type: editType,
        });
      }
      fetchDocs();
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedId || !confirm('Delete this input document?')) return;
    await deleteInputDoc(projectId, selectedId);
    setSelectedId(null);
    fetchDocs();
  };

  const handlePropagate = async () => {
    setPropagating(true);
    try {
      await propagateChanges(projectId);
    } catch {
      // Error handled by axios interceptor
    } finally {
      setPropagating(false);
    }
  };

  if (loading) {
    return <div className="p-4 text-gray-400">Loading input documents...</div>;
  }

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <div className="w-64 border-r border-gray-700 flex flex-col shrink-0">
        <div className="p-2 border-b border-gray-700 flex items-center justify-between">
          <span className="text-xs text-gray-400 font-medium">Input Documents</span>
          {!isViewer && (
            <button
              onClick={handleNew}
              className="text-xs px-2 py-1 bg-blue-600 hover:bg-blue-500 rounded text-white"
            >
              + Add
            </button>
          )}
        </div>
        <div className="flex-1 overflow-auto">
          {docs.length === 0 && !showNew && (
            <div className="p-3 text-xs text-gray-500">No input documents yet.</div>
          )}
          {docs.map((doc) => (
            <button
              key={doc.id}
              onClick={() => handleSelect(doc)}
              className={`w-full text-left px-3 py-2 text-sm border-b border-gray-800 ${
                selectedId === doc.id
                  ? 'bg-gray-700 text-white'
                  : 'text-gray-300 hover:bg-gray-800'
              }`}
            >
              <div className="font-medium truncate">{doc.name}</div>
              <div className="text-xs text-gray-500">
                {doc.doc_type} &middot; v{doc.version}
              </div>
            </button>
          ))}
        </div>
        {!isViewer && (
          <div className="p-2 border-t border-gray-700">
            <button
              onClick={handlePropagate}
              disabled={propagating}
              className="w-full text-xs px-3 py-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 rounded text-white"
            >
              {propagating ? 'Propagating...' : 'Propagate Changes'}
            </button>
          </div>
        )}
      </div>

      {/* Editor */}
      <div className="flex-1 flex flex-col">
        {(selectedDoc || showNew) ? (
          <>
            <div className="p-3 border-b border-gray-700 flex items-center gap-3">
              <input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder="Document name"
                disabled={isViewer}
                className="flex-1 bg-gray-800 text-white px-3 py-1.5 rounded text-sm border border-gray-600"
              />
              <select
                value={editType}
                onChange={(e) => setEditType(e.target.value)}
                disabled={isViewer}
                className="bg-gray-800 text-white px-2 py-1.5 rounded text-sm border border-gray-600"
              >
                <option value="reference">Reference</option>
                <option value="requirements">Requirements</option>
                <option value="constraints">Constraints</option>
              </select>
              {!isViewer && (
                <div className="flex gap-2">
                  <button
                    onClick={handleSave}
                    disabled={saving || !editName.trim()}
                    className="text-xs px-3 py-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded text-white"
                  >
                    {saving ? 'Saving...' : 'Save'}
                  </button>
                  {selectedId && (
                    <button
                      onClick={handleDelete}
                      className="text-xs px-3 py-1.5 bg-red-600 hover:bg-red-500 rounded text-white"
                    >
                      Delete
                    </button>
                  )}
                </div>
              )}
            </div>
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              disabled={isViewer}
              placeholder="Paste your document content here..."
              className="flex-1 bg-gray-900 text-gray-200 p-4 text-sm font-mono resize-none focus:outline-none"
            />
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
            Select a document or add a new one
          </div>
        )}
      </div>
    </div>
  );
}
