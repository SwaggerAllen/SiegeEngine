import { useParams } from 'react-router-dom';
// import { DebugStatePanel } from '../pipeline/DebugStatePanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function DebugTab() {
  const { id: projectId } = useParams<{ id: string }>();
  return (
    <div className="flex-1 overflow-hidden">
      <PanelErrorBoundary fallbackLabel="Debug panel error">
        <div className="p-4 text-gray-400 text-sm">
          Debug panel temporarily disabled for crash investigation.
          Project: {projectId}
        </div>
      </PanelErrorBoundary>
    </div>
  );
}
