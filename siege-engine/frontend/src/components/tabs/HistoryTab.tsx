import { useOutletContext } from 'react-router-dom';
import type { DashboardContext } from './types';
import { EventHistoryPanel } from '../pipeline/EventHistoryPanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function HistoryTab() {
  const { projectId } = useOutletContext<DashboardContext>();
  return (
    <div className="flex-1 overflow-hidden">
      <PanelErrorBoundary fallbackLabel="Event history error">
        <EventHistoryPanel projectId={projectId} />
      </PanelErrorBoundary>
    </div>
  );
}
