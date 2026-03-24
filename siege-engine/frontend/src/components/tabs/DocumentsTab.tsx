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
  const [paneExpanded, setPaneExpanded] = useState(false);
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768);
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)');
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  return (
    <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
      {!paneExpanded && (
        <div className={`${selectedArtifact ? 'h-64 md:h-auto md:w-3/5' : 'flex-1'} border-b md:border-b-0 ${selectedArtifact ? 'md:border-r' : ''} border-gray-700 shrink-0 md:shrink`}>
          {dagHidden ? (
            <div className="h-full flex items-center justify-center text-yellow-400 text-xs">[DEBUG: DAG hidden]</div>
          ) : (
            <PanelErrorBoundary fallbackLabel="DAG render error">
              <PipelineDAG projectId={projectId!} variant="documents" />
            </PanelErrorBoundary>
          )}
        </div>
      )}
      {selectedArtifact && (
        <div className={`flex-1 ${paneExpanded ? 'w-full' : 'md:w-2/5'} flex flex-col overflow-hidden`}>
          <div className="flex items-center justify-end px-3 py-1 border-b border-gray-700 shrink-0">
            <button
              onClick={() => setPaneExpanded(!paneExpanded)}
              className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 hover:text-white text-xs rounded"
              title={paneExpanded ? 'Collapse pane' : 'Expand to full width'}
            >
              {paneExpanded ? '\u21E5 Collapse' : '\u21E4 Expand'}
            </button>
          </div>
          {paneExpanded && isMobile ? (
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="h-1/2 overflow-auto border-b border-gray-700">
                <PanelErrorBoundary fallbackLabel="Editor error">
                  <ArtifactEditor key={selectedArtifact.id} artifact={selectedArtifact} projectId={projectId!} compactMobile />
                </PanelErrorBoundary>
              </div>
              <div className="h-1/2 overflow-auto p-3">
                <PanelErrorBoundary fallbackLabel="Review panel error">
                  <ReviewPanel projectId={projectId!} artifact={selectedArtifact} execution={selectedExecution} compactMobile />
                </PanelErrorBoundary>
              </div>
            </div>
          ) : paneExpanded && (
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
      )}
    </div>
  );
}
