import { useState, useMemo } from 'react';
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
  const [paneExpanded, setPaneExpanded] = useState(false);

  return (
    <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
      {!paneExpanded && !dagHidden && (
        <div className="h-64 md:h-auto md:w-3/5 border-b md:border-b-0 md:border-r border-gray-700 shrink-0 md:shrink">
          <PanelErrorBoundary fallbackLabel="DAG render error">
            <PipelineDAG projectId={projectId!} variant="pipeline" />
          </PanelErrorBoundary>
        </div>
      )}
      {!paneExpanded && dagHidden && (
        <div className="h-64 md:h-auto md:w-3/5 border-b md:border-b-0 md:border-r border-gray-700 shrink-0 md:shrink flex items-center justify-center text-yellow-400 text-xs">
          [DEBUG: DAG hidden]
        </div>
      )}
      <div className={`flex-1 ${paneExpanded ? 'w-full' : 'md:w-2/5'} flex flex-col overflow-hidden`}>
        {selectedArtifact ? (
          <div className="flex-1 flex flex-col overflow-hidden">
            <div className="flex items-center justify-end px-3 py-1 border-b border-gray-700 shrink-0">
              <button
                onClick={() => setPaneExpanded(!paneExpanded)}
                className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 hover:text-white text-xs rounded"
                title={paneExpanded ? 'Collapse pane' : 'Expand to full width'}
              >
                {paneExpanded ? '\u21E5 Collapse' : '\u21E4 Expand'}
              </button>
            </div>
            {paneExpanded && (
              (selectedExecution && ['awaiting_review', 'running', 'ai_review', 'failed'].includes(selectedExecution.status))
              || selectedArtifact.status === 'stale'
            ) ? (
              <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
                <div className="flex-1 md:w-2/3 overflow-auto border-b md:border-b-0 md:border-r border-gray-700">
                  <PanelErrorBoundary fallbackLabel="Editor error">
                    <ArtifactEditor key={selectedArtifact.id} artifact={selectedArtifact} projectId={projectId!} />
                  </PanelErrorBoundary>
                </div>
                <div className="md:w-1/3 overflow-auto p-3">
                  <PanelErrorBoundary fallbackLabel="Review panel error">
                    <ReviewPanel projectId={projectId!} artifact={selectedArtifact} execution={selectedExecution} />
                  </PanelErrorBoundary>
                </div>
              </div>
            ) : (
              <>
                <div className="flex-1 overflow-auto">
                  <PanelErrorBoundary fallbackLabel="Editor error">
                    <ArtifactEditor key={selectedArtifact.id} artifact={selectedArtifact} projectId={projectId!} />
                  </PanelErrorBoundary>
                </div>
                <div className="shrink-0 p-3 border-t border-gray-700 overflow-auto max-h-64">
                  <PanelErrorBoundary fallbackLabel="Review panel error">
                    <ReviewPanel projectId={projectId!} artifact={selectedArtifact} execution={selectedExecution} />
                  </PanelErrorBoundary>
                </div>
              </>
            )}
          </div>
        ) : selectedStageKey ? (
          <PanelErrorBoundary fallbackLabel="Stage config error">
            <StageConfigPanel projectId={projectId!} stageKey={selectedStageKey} />
          </PanelErrorBoundary>
        ) : (
          <div className="flex-1 flex flex-col min-h-0">
            <div className="p-4 text-gray-500 text-sm shrink-0">
              Select a stage node to configure it or start a run
            </div>
            <div className="flex-1 p-4 border-t border-gray-700 overflow-auto min-h-0">
              <PanelErrorBoundary fallbackLabel="Stage status error">
                <StageStatusList executions={executions} projectId={projectId!} />
              </PanelErrorBoundary>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
