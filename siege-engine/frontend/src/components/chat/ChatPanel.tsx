import { useCallback, useEffect, useRef, useState } from 'react';
import { getChatArtifacts, type ChatArtifact } from '../../api/chat';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

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
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [connected, setConnected] = useState(false);
  const [pinnedIds, setPinnedIds] = useState<string[]>([]);
  const [showPinDropdown, setShowPinDropdown] = useState(false);
  const [artifacts, setArtifacts] = useState<ChatArtifact[]>([]);
  const [restoredCount, setRestoredCount] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const streamingContentRef = useRef('');
  const dropdownRef = useRef<HTMLDivElement>(null);
  const connectRef = useRef<() => void>(() => {});
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  // Connect WebSocket with auto-reconnect
  useEffect(() => {
    const token = localStorage.getItem('siege_engine_token');
    if (!token || !projectId) return;

    let ws: WebSocket | null = null;
    let retryDelay = 1000;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let mounted = true;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const url = `${protocol}//${host}/api/chat/${projectId}?token=${token}`;

    function connect() {
      if (!mounted) return;
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }

      ws = new WebSocket(url);

      ws.onopen = () => {
        setConnected(true);
        retryDelay = 1000;
      };

      ws.onclose = (e) => {
        setConnected(false);
        wsRef.current = null;

        // If we were streaming, mark it as interrupted
        setIsStreaming((prev) => {
          if (prev) {
            setMessages((msgs) => {
              const updated = [...msgs];
              const last = updated[updated.length - 1];
              if (last && last.role === 'assistant' && !last.content) {
                updated[updated.length - 1] = {
                  ...last,
                  content: '(connection lost — response may still be generating on the server)',
                };
              }
              return updated;
            });
          }
          return false;
        });

        if (!mounted || e.code === 1000) return;

        const timer = setTimeout(() => {
          retryDelay = Math.min(retryDelay * 2, 30000);
          connect();
        }, retryDelay);
        retryTimerRef.current = timer;
      };

      ws.onerror = (e) => {
        console.error('[Chat WS] Error', e);
      };

      ws.onmessage = (event) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        let data: any;
        try {
          data = JSON.parse(event.data);
        } catch {
          console.error('[Chat WS] Failed to parse message:', event.data);
          return;
        }

        console.log('[Chat WS] Received:', data.type, data);

        switch (data.type) {
          case 'history': {
            const historyMsgs: ChatMessage[] = (data.messages || []).map(
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              (m: any) => ({ role: m.role, content: m.content })
            );
            if (historyMsgs.length > 0) {
              setMessages(historyMsgs);
              setRestoredCount(historyMsgs.length);
              setTimeout(() => setRestoredCount(0), 3000);
            }
            break;
          }

          case 'pins_updated':
            setPinnedIds(data.pinned || []);
            break;

          case 'response_generating': {
            // A response is still being generated from a previous connection.
            // Show thinking indicator and poll for the completed response.
            console.log('[Chat WS] Response still generating from previous connection');
            setIsStreaming(true);
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (last && last.role === 'assistant' && !last.content) return prev;
              return [...prev, { role: 'assistant', content: '' }];
            });
            // Poll every 2s until generation completes
            const pollId = setInterval(() => {
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ type: 'check_generating' }));
              } else {
                clearInterval(pollId);
              }
            }, 2000);
            // Store poll ID so generation_complete can clear it
            (wsRef.current as unknown as { _pollId?: ReturnType<typeof setInterval> })._pollId = pollId;
            break;
          }

          case 'generation_complete': {
            // Generation finished — update messages from fresh history
            setIsStreaming(false);
            const ws = wsRef.current as unknown as { _pollId?: ReturnType<typeof setInterval> };
            if (ws?._pollId) {
              clearInterval(ws._pollId);
              ws._pollId = undefined;
            }
            const freshMsgs: ChatMessage[] = (data.messages || []).map(
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              (m: any) => ({ role: m.role, content: m.content })
            );
            if (freshMsgs.length > 0) {
              setMessages(freshMsgs);
            }
            break;
          }

          case 'response_start':
            setIsStreaming(true);
            streamingContentRef.current = '';
            setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);
            break;

          case 'response_chunk':
            streamingContentRef.current += data.text;
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  content: streamingContentRef.current,
                };
              }
              return updated;
            });
            break;

          case 'response_end':
            setIsStreaming(false);
            if (data.full_text) {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last && last.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    content: data.full_text,
                  };
                }
                return updated;
              });
            }
            break;

          case 'session_reset':
            setMessages([]);
            setPinnedIds([]);
            break;

          case 'error':
            setIsStreaming(false);
            setMessages((prev) => [
              ...prev,
              { role: 'assistant', content: `Error: ${data.message}` },
            ]);
            break;
        }
      };

      wsRef.current = ws;
    }

    connectRef.current = connect;
    connect();

    return () => {
      mounted = false;
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, [projectId]);

  const handleReconnect = () => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    connectRef.current();
  };

  const handleSend = () => {
    if (!input.trim() || !wsRef.current || isStreaming) return;

    const message = input.trim();
    setMessages((prev) => [...prev, { role: 'user', content: message }]);
    wsRef.current.send(JSON.stringify({ type: 'message', content: message }));
    setInput('');
  };

  const handleReset = () => {
    if (!wsRef.current || isStreaming) return;
    wsRef.current.send(JSON.stringify({ type: 'reset' }));
  };

  const handlePin = (artifactId: string) => {
    if (!wsRef.current) return;
    wsRef.current.send(JSON.stringify({ type: 'pin', artifact_id: artifactId }));
    setShowPinDropdown(false);
  };

  const handleUnpin = (artifactId: string) => {
    if (!wsRef.current) return;
    wsRef.current.send(JSON.stringify({ type: 'unpin', artifact_id: artifactId }));
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
              onClick={handleReconnect}
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
          onClick={handleReset}
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
                  onClick={() => handleUnpin(art.id)}
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
                          onClick={() => handlePin(art.id)}
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
