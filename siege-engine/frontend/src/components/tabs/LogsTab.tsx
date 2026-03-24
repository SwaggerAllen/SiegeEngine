import { LogPanel } from '../pipeline/LogPanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function LogsTab() {
  return (
    <div className="flex-1 overflow-hidden">
      <PanelErrorBoundary fallbackLabel="Log panel error">
        <LogPanel />
      </PanelErrorBoundary>
    </div>
  );
}
