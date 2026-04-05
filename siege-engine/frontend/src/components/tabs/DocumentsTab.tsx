import { useState, useMemo, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useDAGStore } from '../../store/dagStore';
import { usePipelineUIStore } from '../../store/pipelineUIStore';
import { useArtifact } from '../../hooks/queries/useProjectQueries';
import { useExecutions } from '../../hooks/queries/usePipelineQueries';
import { findSelectedExecution } from '../../pages/ProjectDashboardLayout';
import { PipelineDAG } from '../dag/PipelineDAG';
import { ArtifactEditor } from '../editor/ArtifactEditor';
import { ArtifactPromptDebugView } from '../editor/ArtifactPromptDebugView';
import { ReviewPanel } from '../pipeline/ReviewPanel';
import { BottomPane, ArtifactStatusBadge } from '../pipeline/BottomPane';
import { PanelErrorBoundary } from '../ErrorBoundary';

export function DocumentsTab() {
  const { id: projectId } = useParams<{ id: string }>();
  const dagHidden = usePipelineUIStore((s) => s.dagHidden);
  const selectedArtifactId = useDAGStore((s) => s.selectedArtifactId);
  const { data: selectedArtifact = null } = useArtifact(selectedArtifactId);
  const executions = useExecutions(projectId!);
  const selectedExecution = useMemo(
    () => (selectedArtifact ? findSelectedExecution(executions, selectedArtifact) : undefined),
    [executions, selectedArtifact],
  );

  // Pane + view mode state
  const [paneOpen, setPaneOpen] = useState(false);
  const [viewMode, setViewMode] = useState<'dag' | 'review' | 'edit' | 'prompt'>('dag');

  // Auto-open pane when a node is selected; close+reset on deselect
  useEffect(() => {
    if (selectedArtifact) {
      setPaneOpen(true);
    } else {
      setPaneOpen(false);
      setViewMode('dag');
    }
  }, [selectedArtifact?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const btnClass = (active: boolean) =>
    `px-2 py-0.5 text-xs rounded shrink-0 ${
      active
        ? 'bg-blue-600 text-white hover:bg-blue-500'
        : 'bg-gray-700 text-gray-300 hover:bg-gray-600 hover:text-white'
    }`;

  const paneHandle = (
    <>
      {selectedArtifact ? (
        <>
          <span className="text-xs font-mono text-gray-300 truncate min-w-0 flex-1">
            {selectedArtifact.component_key ?? selectedArtifact.artifact_type}
          </span>
          <ArtifactStatusBadge status={selectedArtifact.status} />
          {viewMode === 'dag' ? (
            <>
              <button onClick={(e) => { e.stopPropagation(); setViewMode('review'); setPaneOpen(true); }} className={btnClass(false)}>Review</button>
              <button onClick={(e) => { e.stopPropagation(); setViewMode('edit'); setPaneOpen(true); }} className={btnClass(false)}>Edit</button>
              <button onClick={(e) => { e.stopPropagation(); setViewMode('prompt'); setPaneOpen(true); }} className="px-2 py-0.5 text-xs rounded shrink-0 bg-purple-900/60 text-purple-300 hover:bg-purple-800 hover:text-white">Prompt</button>
            </>
          ) : (
            <>
              <button onClick={(e) => { e.stopPropagation(); setViewMode('dag'); }} className={btnClass(false)}>← DAG</button>
              {viewMode === 'review' ? (
                <button onClick={(e) => { e.stopPropagation(); setViewMode('edit'); }} className={btnClass(false)}>✏ Edit</button>
              ) : viewMode === 'edit' ? (
                <button onClick={(e) => { e.stopPropagation(); setViewMode('review'); }} className={btnClass(false)}>👁 View</button>
              ) : null}
            </>
          )}
        </>
      ) : (
        <span className="text-gray-500 text-xs flex-1">Select a node to review</span>
      )}
    </>
  );

  return (
    <div className="flex-1 relative overflow-hidden">
      {/* Main area: DAG fills the whole container; editors overlay when active */}
      {selectedArtifact && viewMode === 'review' ? (
        <div className="absolute inset-0">
          <PanelErrorBoundary fallbackLabel="Viewer error">
            <ArtifactEditor key={selectedArtifact.id} artifact={selectedArtifact} projectId={projectId!} viewOnly={true} />
          </PanelErrorBoundary>
        </div>
      ) : selectedArtifact && viewMode === 'edit' ? (
        <div className="absolute inset-0">
          <PanelErrorBoundary fallbackLabel="Editor error">
            <ArtifactEditor key={selectedArtifact.id} artifact={selectedArtifact} projectId={projectId!} viewOnly={false} />
          </PanelErrorBoundary>
        </div>
      ) : selectedArtifact && viewMode === 'prompt' ? (
        <div className="absolute inset-0">
          <PanelErrorBoundary fallbackLabel="Prompt preview error">
            <ArtifactPromptDebugView projectId={projectId!} artifactId={selectedArtifact.id} />
          </PanelErrorBoundary>
        </div>
      ) : dagHidden ? (
        <div className="absolute inset-0 flex items-center justify-center text-yellow-400 text-xs">
          [DEBUG: DAG hidden]
        </div>
      ) : (
        <div className="absolute inset-0">
          <PanelErrorBoundary fallbackLabel="DAG render error">
            <PipelineDAG projectId={projectId!} variant="documents" />
          </PanelErrorBoundary>
        </div>
      )}

      {/* Bottom action pane — overlays on top of DAG, never changes DAG dimensions */}
      <BottomPane handle={paneHandle} open={paneOpen} onOpenChange={setPaneOpen}>
        {selectedArtifact ? (
          <div className="p-3">
            <PanelErrorBoundary fallbackLabel="Review panel error">
              <ReviewPanel
                projectId={projectId!}
                artifact={selectedArtifact}
                execution={selectedExecution}
                executions={executions}
                mode={viewMode === 'review' ? 'feedback' : 'actions'}
              />
            </PanelErrorBoundary>
          </div>
        ) : (
          <div className="p-4 text-gray-500 text-sm">Select a node to see review options.</div>
        )}
      </BottomPane>
    </div>
  );
}
