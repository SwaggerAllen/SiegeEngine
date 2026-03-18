import { useEffect, useState } from 'react';
import {
  listInputDocs,
  createInputDoc,
  updateInputDoc,
  deleteInputDoc,
  propagateChanges,
  type InputDocument,
} from '../../api/inputDocs';
import { getArtifact, updateArtifact } from '../../api/projects';
import { useProjectStore } from '../../store/projectStore';
import { useAuthStore } from '../../store/authStore';
import type { Artifact } from '../../types/project';

interface InputDocsPanelProps {
  projectId: string;
}

/** Max characters shown as preview in the list view. */
const PREVIEW_LENGTH = 200;

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + '...';
}

type ViewItem =
  | { kind: 'project_doc'; artifact: Artifact }
  | { kind: 'input_doc'; doc: InputDocument };

export default function InputDocsPanel({ projectId }: InputDocsPanelProps) {
  const { user } = useAuthStore();
  const isViewer = user?.role === 'viewer';
  const { currentProject } = useProjectStore();

  const [inputDocs, setInputDocs] = useState<InputDocument[]>([]);
  const [projectDocArtifact, setProjectDocArtifact] = useState<Artifact | null>(null);
  const [loading, setLoading] = useState(true);

  // Detail view state
  const [selected, setSelected] = useState<ViewItem | null>(null);
  const [editName, setEditName] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editType, setEditType] = useState('reference');
  const [saving, setSaving] = useState(false);
  const [propagating, setPropagating] = useState(false);
  const [isNew, setIsNew] = useState(false);
  const [_dirty, setDirty] = useState(false);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const docs = await listInputDocs(projectId);
      setInputDocs(docs);

      // Find the project_doc artifact from the current project
      const projectDocSummary = currentProject?.artifacts.find(
        (a) => a.artifact_type === 'project_doc'
      );
      if (projectDocSummary) {
        const full = await getArtifact(projectDocSummary.id);
        setProjectDocArtifact(full);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
  }, [projectId, currentProject?.id]);

  const openItem = (item: ViewItem) => {
    setSelected(item);
    setIsNew(false);
    setDirty(false);
    if (item.kind === 'project_doc') {
      setEditName('Project Document');
      setEditContent(item.artifact.content ?? '');
      setEditType('reference');
    } else {
      setEditName(item.doc.name);
      setEditContent(item.doc.content);
      setEditType(item.doc.doc_type);
    }
  };

  const openNew = () => {
    setSelected(null);
    setIsNew(true);
    setDirty(false);
    setEditName('');
    setEditContent('');
    setEditType('reference');
  };

  const backToList = () => {
    setSelected(null);
    setIsNew(false);
    setDirty(false);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      if (isNew) {
        await createInputDoc(projectId, {
          name: editName,
          content: editContent,
          doc_type: editType,
        });
        setIsNew(false);
      } else if (selected?.kind === 'project_doc') {
        await updateArtifact(selected.artifact.id, editContent);
      } else if (selected?.kind === 'input_doc') {
        await updateInputDoc(projectId, selected.doc.id, {
          name: editName,
          content: editContent,
          doc_type: editType,
        });
      }
      setDirty(false);
      await fetchAll();
      backToList();
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selected || selected.kind !== 'input_doc') return;
    if (!confirm('Delete this input document?')) return;
    await deleteInputDoc(projectId, selected.doc.id);
    await fetchAll();
    backToList();
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
    return <div className="p-4 text-gray-400">Loading documents...</div>;
  }

  // ── Detail / Edit View ──────────────────────────────────────────────
  if (selected || isNew) {
    const isProjectDoc = selected?.kind === 'project_doc';
    return (
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="p-3 border-b border-gray-700 flex items-center gap-3">
          <button
            onClick={backToList}
            className="text-xs px-2 py-1 text-gray-400 hover:text-white hover:bg-gray-700 rounded"
          >
            &larr; Back
          </button>
          {isProjectDoc ? (
            <span className="flex-1 text-sm font-medium text-white">Project Document</span>
          ) : (
            <input
              value={editName}
              onChange={(e) => {
                setEditName(e.target.value);
                setDirty(true);
              }}
              placeholder="Document name"
              disabled={isViewer}
              className="flex-1 bg-gray-800 text-white px-3 py-1.5 rounded text-sm border border-gray-600"
            />
          )}
          {!isProjectDoc && (
            <select
              value={editType}
              onChange={(e) => {
                setEditType(e.target.value);
                setDirty(true);
              }}
              disabled={isViewer}
              className="bg-gray-800 text-white px-2 py-1.5 rounded text-sm border border-gray-600"
            >
              <option value="reference">Reference</option>
              <option value="requirements">Requirements</option>
              <option value="constraints">Constraints</option>
            </select>
          )}
          {!isViewer && (
            <div className="flex gap-2">
              <button
                onClick={handleSave}
                disabled={saving || (!isProjectDoc && !editName.trim())}
                className="text-xs px-3 py-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded text-white"
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
              {selected?.kind === 'input_doc' && (
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

        {/* Editor */}
        <textarea
          value={editContent}
          onChange={(e) => {
            setEditContent(e.target.value);
            setDirty(true);
          }}
          disabled={isViewer}
          placeholder="Paste your document content here..."
          className="flex-1 bg-gray-900 text-gray-200 p-4 text-sm font-mono resize-none focus:outline-none"
        />
      </div>
    );
  }

  // ── List View ───────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-3 border-b border-gray-700 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-300">Documents</span>
        <div className="flex gap-2">
          {!isViewer && (
            <>
              <button
                onClick={openNew}
                className="text-xs px-3 py-1.5 bg-blue-600 hover:bg-blue-500 rounded text-white"
              >
                + New Document
              </button>
              <button
                onClick={handlePropagate}
                disabled={propagating}
                className="text-xs px-3 py-1.5 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 rounded text-white"
              >
                {propagating ? 'Propagating...' : 'Propagate Changes'}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-auto p-3 space-y-2">
        {/* Project Document card */}
        {projectDocArtifact && (
          <button
            onClick={() => openItem({ kind: 'project_doc', artifact: projectDocArtifact })}
            className="w-full text-left p-3 rounded border border-gray-700 hover:border-gray-500 bg-gray-800/50 hover:bg-gray-800 transition-colors"
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm font-medium text-white">Project Document</span>
              <span className="text-xs px-1.5 py-0.5 rounded bg-indigo-900/50 text-indigo-300">
                project doc
              </span>
              <span className="text-xs text-gray-500">v{projectDocArtifact.version}</span>
            </div>
            <p className="text-xs text-gray-400 leading-relaxed whitespace-pre-line">
              {truncate(projectDocArtifact.content ?? '', PREVIEW_LENGTH)}
            </p>
          </button>
        )}

        {/* Input Document cards */}
        {inputDocs.map((doc) => (
          <button
            key={doc.id}
            onClick={() => openItem({ kind: 'input_doc', doc })}
            className="w-full text-left p-3 rounded border border-gray-700 hover:border-gray-500 bg-gray-800/50 hover:bg-gray-800 transition-colors"
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm font-medium text-white">{doc.name}</span>
              <span className="text-xs px-1.5 py-0.5 rounded bg-gray-700 text-gray-300">
                {doc.doc_type}
              </span>
              <span className="text-xs text-gray-500">v{doc.version}</span>
            </div>
            <p className="text-xs text-gray-400 leading-relaxed whitespace-pre-line">
              {truncate(doc.content, PREVIEW_LENGTH)}
            </p>
          </button>
        ))}

        {inputDocs.length === 0 && !projectDocArtifact && (
          <div className="text-center text-gray-500 text-sm py-8">
            No documents yet. Add one to get started.
          </div>
        )}
      </div>
    </div>
  );
}
