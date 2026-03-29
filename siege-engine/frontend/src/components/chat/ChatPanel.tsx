import { useCallback, useEffect, useRef, useState } from 'react';
import { getChatArtifacts, type ChatArtifact } from '../../api/chat';
import { chatManager, useChatStore } from '../../store/chatStore';

interface ChatPanelProps {
  projectId: string;
}

// Group artifacts by type for the pin dropdown
const TYPE_LABELS: Record<string, string> = {
  feature_expansion: 'Features',
  system_architecture: 'Architecture',
  component_architecture: 'Component Architecture',
  component_map: 'Components',
  component_plan: 'Component Plans',
  sub_component_map: 'Sub-Components',
  sub_component_architecture: 'Sub-Component Architecture',
  sub_component_plan: 'Sub-Component Plans',
  code: 'Code',
  code_review: 'Code Review',
  system_requirements: 'Requirements',
};

function groupArtifacts(artifacts: ChatArtifact[]) {
  const groups: Record<string, ChatArtifact[]> = {};
  for (const a of artifacts) {
    const label = TYPE_LABELS[a.artifact_type] || a.artifact_type;
    if (!groups[label]) groups[label] = [];
    groups[label].push(a);
  }
  return groups;
}

export function ChatPanel({ projectId }: ChatPanelProps) {
  const { messages, isStreaming, connected, pinnedIds, restoredCount } = useChatStore();

  const [input, setInput] = useState('');
  const [showPinDropdown, setShowPinDropdown] = useState(false);
  const [artifacts, setArtifacts] = useState<ChatArtifact[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Connect to project (idempotent — no-op if already connected)
  useEffect(() => {
    chatManager.connectToProject(projectId);
  }, [projectId]);

  // Scroll to bottom on new messages
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Close dropdown on outside click
  useEffect(() => {
    if (!showPinDropdown) return;
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowPinDropdown(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showPinDropdown]);

  // Load artifacts for pin dropdown
  useEffect(() => {
    if (!showPinDropdown || !projectId) return;
    getChatArtifacts(projectId).then(setArtifacts).catch(console.error);
  }, [showPinDropdown, projectId]);

  const handleSend = () => {
    if (!input.trim() || isStreaming) return;
    chatManager.sendMessage(input.trim());
    setInput('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const pinnedArtifactNames = pinnedIds
    .map((id) => artifacts.find((a) => a.id === id))
    .filter(Boolean);

  const grouped = groupArtifacts(artifacts.filter((a) => !pinnedIds.includes(a.id)));

  return (
    <div className="flex flex-col h-full bg-gray-900">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700 shrink-0">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-white">Chat</h3>
          <span
            className={`w-2 h-2 rounded-full ${
              connected ? 'bg-green-400' : 'bg-red-400'
            }`}
          />
          {!connected && (
            <button
              onClick={() => chatManager.reconnect()}
              className="text-xs text-red-400 hover:text-red-300 underline"
            >
              Reconnect
            </button>
          )}
          {restoredCount > 0 && (
            <span className="text-xs text-gray-400 animate-pulse">
              Restored {restoredCount} messages
            </span>
          )}
        </div>
        <button
          onClick={() => chatManager.resetSession()}
          disabled={isStreaming}
          className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
        >
          New Chat
        </button>
      </div>

      {/* Pinned artifacts chips */}
      {pinnedIds.length > 0 && (
        <div className="flex flex-wrap gap-1 px-4 py-2 border-b border-gray-700">
          {pinnedArtifactNames.map((art) =>
            art ? (
              <span
                key={art.id}
                className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-900/50 text-blue-300 text-xs rounded-full border border-blue-700"
              >
                {art.component_key ? `${art.component_key}` : art.name}
                <button
                  onClick={() => chatManager.unpin(art.id)}
                  className="hover:text-blue-100 ml-0.5"
                  title="Unpin"
                >
                  ×
                </button>
              </span>
            ) : null
          )}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-auto px-4 py-3 space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-500 text-sm text-center">
              Chat with Claude about this project.<br />
              Claude has read-only access to the project's git repository.<br />
              <span className="text-gray-600">
                Use the + button to pin documents into context.
              </span>
            </p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] md:max-w-[70%] px-3 py-2 rounded-lg text-sm whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-200 border border-gray-700'
              }`}
            >
              {msg.content || (
                <span className="text-gray-500 animate-pulse">Thinking...</span>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-700 px-3 py-2 shrink-0">
        <div className="flex gap-2">
          {/* Pin button */}
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setShowPinDropdown(!showPinDropdown)}
              className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm rounded-lg min-h-[44px]"
              title="Pin a document to context"
            >
              +
            </button>
            {showPinDropdown && (
              <div className="absolute bottom-full left-0 mb-1 w-72 max-h-80 overflow-auto bg-gray-800 border border-gray-600 rounded-lg shadow-xl z-50">
                {Object.keys(grouped).length === 0 ? (
                  <div className="px-3 py-2 text-gray-500 text-xs">
                    No artifacts available
                  </div>
                ) : (
                  Object.entries(grouped).map(([label, items]) => (
                    <div key={label}>
                      <div className="px-3 py-1 text-xs text-gray-400 font-medium bg-gray-900/50 sticky top-0">
                        {label}
                      </div>
                      {items.map((art) => (
                        <button
                          key={art.id}
                          onClick={() => {
                            chatManager.pin(art.id);
                            setShowPinDropdown(false);
                          }}
                          className="w-full text-left px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-700 truncate"
                        >
                          {art.component_key
                            ? `${art.component_key}`
                            : art.name}
                          <span className="text-gray-500 text-xs ml-2">
                            {art.status}
                          </span>
                        </button>
                      ))}
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message..."
            rows={1}
            className="flex-1 px-3 py-2 bg-gray-800 text-white text-sm rounded-lg border border-gray-600 focus:border-blue-500 focus:outline-none resize-none min-h-[44px]"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isStreaming || !connected}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg disabled:opacity-50 shrink-0 min-h-[44px]"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
