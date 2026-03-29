import { useParams } from 'react-router-dom';
import { ChatPanel } from '../chat/ChatPanel';
import { PanelErrorBoundary } from '../ErrorBoundary';
import { debugLog } from '../../lib/debugLog';

export default function ChatTab() {
  const { id: projectId } = useParams<{ id: string }>();
  debugLog('ChatTab', `render projectId=${projectId}`);
  return (
    <div className="flex-1 overflow-hidden">
      <PanelErrorBoundary fallbackLabel="Chat error">
        <ChatPanel projectId={projectId!} />
      </PanelErrorBoundary>
    </div>
  );
}
