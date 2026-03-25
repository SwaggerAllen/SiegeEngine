import { useState, useMemo, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useDAGStore } from '../../store/dagStore';
import { usePipelineUIStore } from '../../store/pipelineUIStore';
import { useArtifact } from '../../hooks/queries/useProjectQueries';
import { useExecutions } from '../../hooks/queries/usePipelineQueries';
import { findSelectedExecution } from '../../pages/ProjectDashboardLayout';
import { PipelineDAG } from '../dag/PipelineDAG';
import { ArtifactEditor } from '../editor/ArtifactEditor';
import { ReviewPanel } from '../pipeline/ReviewPanel';
import { StageConfigPanel } from '../pipeline/StageConfigPanel';
import { StageStatusList } from '../pipeline/StageStatus';
import { BottomPane, ArtifactStatusBadge } from '../pipeline/BottomPane';
import { PanelErrorBoundary } from '../ErrorBoundary';

export function PipelineTab() {
  const { id: projectId } = useParams<{ id: string }>();
  const dagHidden = usePipelineUIStore((s) => s.dagHidden);
  const selectedStageKey = useDAGStore((s) => s.selectedStageKey);
  const selectedArtifactId = useDAGStore((s) => s.selectedArtifactId);
  const { data: selectedArtifact = null } = useArtifact(selectedArtifactId);
  const executions = useExecutions(projectId!);
  const selectedExecution = useMemo(
    () => (selectedArtifact ? findSelectedExecution(executions, selectedArtifact) : undefined),
    [executions, selectedArtifact],
  );

  // Pane + view mode state
  const [paneOpen, setPaneOpen] = useState(true);
  const [viewMode, setViewMode] = useState<'dag' | 'review' | 'edit'>('dag');

  // Auto-open on selection; reset view mode on deselect
  useEffect(() => {
    if (selectedArtifact) {
      setPaneOpen(true);
    } else if (selectedStageKey) {
      setPaneOpen(true);
      setViewMode('dag');
    } else {
      setViewMode('dag');
    }
  }, [selectedArtifact?.id, selectedStageKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const btnClass = (active: boolean) =>
    `px-2 py-0.5 text-xs rounded shrink-0 ${
      active
        ? 'bg-blue-600 text-white hover:bg-blue-500'
        : 'bg-gray-700 text-gray-300 hover:bg-gray-600 hover:text-white'
    }`;

  // Build pane handle content
  let paneHandle;
  if (selectedArtifact) {
    paneHandle = (
      <>
        <span className="text-xs font-mono text-gray-300 truncate min-w-0 flex-1">
          {selectedArtifact.component_key ?? selectedArtifact.artifact_type}
        </span>
        <ArtifactStatusBadge status={selectedArtifact.status} />
        {viewMode === 'dag' ? (
          <>
            <button onClick={(e) => { e.stopPropagation(); setViewMode('review'); setPaneOpen(true); }} className={btnClass(false)}>Review</button>
            <button onClick={(e) => { e.stopPropagation(); setViewMode('edit'); setPaneOpen(true); }} className={btnClass(false)}>Edit</button>
          </>
        ) : (
          <>
            <button onClick={(e) => { e.stopPropagation(); setViewMode('dag'); }} className={btnClass(false)}>← DAG</button>
            {viewMode === 'review' ? (
              <button onClick={(e) => { e.stopPropagation(); setViewMode('edit'); }} className={btnClass(false)}>✏ Edit</button>
            ) : (
              <button onClick={(e) => { e.stopPropagation(); setViewMode('review'); }} className={btnClass(false)}>👁 View</button>
            )}
          </>
        )}
      </>
    );
  } else if (selectedStageKey) {
    paneHandle = (
      <>
        <span className="text-xs font-mono text-gray-300 truncate min-w-0 flex-1">{selectedStageKey}</span>
        <span className="text-xs text-gray-500 shrink-0">Stage config</span>
      </>
    );
  } else {
    paneHandle = <span className="text-gray-500 text-xs flex-1">Pipeline stages</span>;
  }

  // Build pane content
  let paneContent;
  if (selectedArtifact) {
    paneContent = (
      <div className="p-3">
        <PanelErrorBoundary fallbackLabel="Review panel error">
          <ReviewPanel
            projectId={projectId!}
            artifact={selectedArtifact}
            execution={selectedExecution}
            mode={viewMode === 'review' ? 'feedback' : 'actions'}
          />
        </PanelErrorBoundary>
      </div>
    );
  } else if (selectedStageKey) {
    paneContent = (
      <PanelErrorBoundary fallbackLabel="Stage config error">
        <StageConfigPanel projectId={projectId!} stageKey={selectedStageKey} />
      </PanelErrorBoundary>
    );
  } else {
    paneContent = (
      <div className="p-3">
        <PanelErrorBoundary fallbackLabel="Stage status error">
          <StageStatusList executions={executions} projectId={projectId!} />
        </PanelErrorBoundary>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Main area: DAG, markdown view, or editor */}
      <div className="flex-1 overflow-hidden">
        {selectedArtifact && viewMode === 'review' ? (
          <PanelErrorBoundary fallbackLabel="Viewer error">
            <ArtifactEditor key={selectedArtifact.id} artifact={selectedArtifact} projectId={projectId!} viewOnly={true} />
          </PanelErrorBoundary>
        ) : selectedArtifact && viewMode === 'edit' ? (
          <PanelErrorBoundary fallbackLabel="Editor error">
            <ArtifactEditor key={selectedArtifact.id} artifact={selectedArtifact} projectId={projectId!} viewOnly={false} />
          </PanelErrorBoundary>
        ) : dagHidden ? (
          <div className="h-full flex items-center justify-center text-yellow-400 text-xs">
            [DEBUG: DAG hidden]
          </div>
        ) : (
          <PanelErrorBoundary fallbackLabel="DAG render error">
            <PipelineDAG projectId={projectId!} variant="pipeline" />
          </PanelErrorBoundary>
        )}
      </div>

      {/* Bottom action pane */}
      <BottomPane handle={paneHandle} open={paneOpen} onOpenChange={setPaneOpen}>
        {paneContent}
      </BottomPane>
    </div>
  );
}
