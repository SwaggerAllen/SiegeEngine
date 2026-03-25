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

  // Pane + review mode state
  const [paneOpen, setPaneOpen] = useState(true);
  const [reviewMode, setReviewMode] = useState(false);

  // Auto-open on selection; reset review mode on deselect
  useEffect(() => {
    if (selectedArtifact) {
      setPaneOpen(true);
    } else if (selectedStageKey) {
      setPaneOpen(true);
      setReviewMode(false);
    } else {
      setReviewMode(false);
    }
  }, [selectedArtifact?.id, selectedStageKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Build pane handle content
  let paneHandle;
  if (selectedArtifact) {
    paneHandle = (
      <>
        <span className="text-xs font-mono text-gray-300 truncate min-w-0 flex-1">
          {selectedArtifact.component_key ?? selectedArtifact.artifact_type}
        </span>
        <ArtifactStatusBadge status={selectedArtifact.status} />
        <button
          onClick={(e) => {
            e.stopPropagation();
            setReviewMode((m) => !m);
            setPaneOpen(true);
          }}
          className={`px-2 py-0.5 text-xs rounded shrink-0 ${
            reviewMode
              ? 'bg-blue-600 text-white hover:bg-blue-500'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600 hover:text-white'
          }`}
        >
          {reviewMode ? '← DAG' : 'Review'}
        </button>
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
            mode={reviewMode ? 'feedback' : 'actions'}
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
      {/* Main area: DAG or document editor in review mode */}
      <div className="flex-1 overflow-hidden">
        {reviewMode && selectedArtifact ? (
          <PanelErrorBoundary fallbackLabel="Editor error">
            <ArtifactEditor key={selectedArtifact.id} artifact={selectedArtifact} projectId={projectId!} />
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
