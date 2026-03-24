import { useParams } from 'react-router-dom';
import { ChatPanel } from '../chat/ChatPanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function ChatTab() {
  const { id: projectId } = useParams<{ id: string }>();
  return (
    <div className="flex-1 overflow-hidden">
      <PanelErrorBoundary fallbackLabel="Chat error">
        <ChatPanel projectId={projectId!} />
      </PanelErrorBoundary>
    </div>
  );
}
