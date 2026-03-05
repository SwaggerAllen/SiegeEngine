import { useCallback, useEffect, useRef, useState } from 'react';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

interface ChatPanelProps {
  projectId: string;
}

export function ChatPanel({ projectId }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const streamingContentRef = useRef('');

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Connect WebSocket
  useEffect(() => {
    const token = localStorage.getItem('siege_engine_token');
    if (!token || !projectId) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const url = `${protocol}//${host}/api/chat/${projectId}?token=${token}`;

    const ws = new WebSocket(url);

    ws.onopen = () => {
      setConnected(true);
    };

    ws.onclose = () => {
      setConnected(false);
    };

    ws.onerror = (e) => {
      console.error('[Chat WS] Error', e);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
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
    return () => ws.close();
  }, [projectId]);

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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

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
        </div>
        <button
          onClick={handleReset}
          disabled={isStreaming}
          className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded disabled:opacity-50 min-h-[44px] md:min-h-0"
        >
          New Chat
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-auto px-4 py-3 space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-500 text-sm text-center">
              Chat with Claude about this project.<br />
              Claude has access to the project's git repository.
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
