import { useOutletContext } from 'react-router-dom';
import type { DashboardContext } from './types';
import { DebugStatePanel } from '../pipeline/DebugStatePanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function DebugTab() {
  const { projectId } = useOutletContext<DashboardContext>();
  return (
    <div className="flex-1 overflow-hidden">
      <PanelErrorBoundary fallbackLabel="Debug panel error">
        <DebugStatePanel projectId={projectId} />
      </PanelErrorBoundary>
    </div>
  );
}
