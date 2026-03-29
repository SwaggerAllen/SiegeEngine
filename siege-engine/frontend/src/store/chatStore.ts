/**
 * Zustand store that owns the chat WebSocket connection.
 *
 * The WS stays alive across tab switches within the same project.
 * ChatPanel subscribes to this store instead of managing its own WS.
 */

import { debugLog } from '../lib/debugLog';

// ── Types ──────────────────────────────────────────────────────────────────

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

interface ChatState {
  // Connection
  projectId: string | null;
  connected: boolean;
  // Messages
  messages: ChatMessage[];
  isStreaming: boolean;
  restoredCount: number;
  // Pins
  pinnedIds: string[];
}

type Listener = () => void;

// ── Singleton chat manager ─────────────────────────────────────────────────

class ChatManager {
  private ws: WebSocket | null = null;
  private projectId: string | null = null;
  private retryDelay = 1000;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private mounted = false;
  private streamingContent = '';
  private restoredCountTimer: ReturnType<typeof setTimeout> | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;

  // Observable state
  private _state: ChatState = {
    projectId: null,
    connected: false,
    messages: [],
    isStreaming: false,
    restoredCount: 0,
    pinnedIds: [],
  };

  private listeners = new Set<Listener>();

  // ── Public API ─────────────────────────────────────────────────────

  get state(): Readonly<ChatState> {
    return this._state;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Ensure we're connected to the given project.
   * If already connected to the same project, this is a no-op.
   * If connected to a different project, disconnect first.
   */
  connectToProject(projectId: string) {
    if (this.projectId === projectId && this.ws?.readyState === WebSocket.OPEN) {
      return; // already connected
    }
    if (this.projectId === projectId && this.ws?.readyState === WebSocket.CONNECTING) {
      return; // connection in progress
    }

    // Different project or not connected
    if (this.projectId !== projectId) {
      this.disconnect();
      this.projectId = projectId;
      this.setState({
        projectId,
        messages: [],
        pinnedIds: [],
        isStreaming: false,
        restoredCount: 0,
      });
    }

    this.mounted = true;
    this.connect();
  }

  /** Force disconnect (e.g., on logout or project switch). */
  disconnect() {
    this.mounted = false;
    this.clearRetryTimer();
    this.clearPollTimer();
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.projectId = null;
    this.setState({ connected: false, projectId: null });
  }

  /** Manual reconnect button. */
  reconnect() {
    this.clearRetryTimer();
    this.retryDelay = 1000;
    this.connect();
  }

  sendMessage(content: string) {
    if (!content.trim() || !this.ws || this._state.isStreaming) return;
    this.setState({
      messages: [...this._state.messages, { role: 'user', content }],
    });
    this.ws.send(JSON.stringify({ type: 'message', content }));
  }

  resetSession() {
    if (!this.ws || this._state.isStreaming) return;
    this.ws.send(JSON.stringify({ type: 'reset' }));
  }

  pin(artifactId: string) {
    this.ws?.send(JSON.stringify({ type: 'pin', artifact_id: artifactId }));
  }

  unpin(artifactId: string) {
    this.ws?.send(JSON.stringify({ type: 'unpin', artifact_id: artifactId }));
  }

  // ── Internal ───────────────────────────────────────────────────────

  private connect() {
    if (!this.mounted || !this.projectId) return;

    const token = localStorage.getItem('siege_engine_token');
    if (!token) {
      debugLog('ChatWS', 'No token, skipping connect');
      return;
    }

    debugLog('ChatWS', `Connecting to project ${this.projectId}`);
    this.clearRetryTimer();

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const url = `${protocol}//${host}/api/chat/${this.projectId}?token=${token}`;

    const ws = new WebSocket(url);

    ws.onopen = () => {
      debugLog('ChatWS', 'Connected');
      this.setState({ connected: true });
      this.retryDelay = 1000;
    };

    ws.onclose = (e) => {
      debugLog('ChatWS', `Closed code=${e.code}`);
      this.ws = null;
      this.setState({ connected: false });

      // Mark interrupted streaming
      if (this._state.isStreaming) {
        const msgs = [...this._state.messages];
        const last = msgs[msgs.length - 1];
        if (last?.role === 'assistant' && !last.content) {
          msgs[msgs.length - 1] = {
            ...last,
            content: '(connection lost — response may still be generating on the server)',
          };
        }
        this.setState({ messages: msgs, isStreaming: false });
      }

      if (!this.mounted || e.code === 1000) return;

      // Auto-reconnect with backoff
      this.retryTimer = setTimeout(() => {
        this.retryDelay = Math.min(this.retryDelay * 2, 30000);
        this.connect();
      }, this.retryDelay);
    };

    ws.onerror = () => {
      debugLog('ChatWS', 'Connection error');
    };

    ws.onmessage = (event) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let data: any;
      try {
        data = JSON.parse(event.data);
      } catch {
        debugLog('ChatWS', `Failed to parse: ${event.data}`);
        return;
      }

      debugLog('ChatWS', `Recv: ${data.type}`);
      this.handleEvent(data);
    };

    this.ws = ws;
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private handleEvent(data: any) {
    switch (data.type) {
      case 'history': {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const msgs: ChatMessage[] = (data.messages || []).map((m: any) => ({
          role: m.role,
          content: m.content,
        }));
        debugLog('ChatWS', `History: ${msgs.length} msgs`);
        if (msgs.length > 0) {
          this.setState({ messages: msgs, restoredCount: msgs.length });
          if (this.restoredCountTimer) clearTimeout(this.restoredCountTimer);
          this.restoredCountTimer = setTimeout(
            () => this.setState({ restoredCount: 0 }),
            3000,
          );
        }
        break;
      }

      case 'pins_updated':
        this.setState({ pinnedIds: data.pinned || [] });
        break;

      case 'response_generating':
        debugLog('ChatWS', 'Generation in progress from previous connection');
        this.setState({ isStreaming: true });
        // Add thinking placeholder if not already there
        {
          const msgs = [...this._state.messages];
          const last = msgs[msgs.length - 1];
          if (!last || last.role !== 'assistant' || last.content) {
            msgs.push({ role: 'assistant', content: '' });
            this.setState({ messages: msgs });
          }
        }
        this.startPolling();
        break;

      case 'generation_complete': {
        this.clearPollTimer();
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const msgs: ChatMessage[] = (data.messages || []).map((m: any) => ({
          role: m.role,
          content: m.content,
        }));
        this.setState({ isStreaming: false });
        if (msgs.length > 0) {
          this.setState({ messages: msgs });
        }
        break;
      }

      case 'response_start':
        this.streamingContent = '';
        this.setState({
          isStreaming: true,
          messages: [...this._state.messages, { role: 'assistant', content: '' }],
        });
        break;

      case 'response_chunk':
        this.streamingContent += data.text;
        {
          const msgs = [...this._state.messages];
          const last = msgs[msgs.length - 1];
          if (last?.role === 'assistant') {
            msgs[msgs.length - 1] = { ...last, content: this.streamingContent };
            this.setState({ messages: msgs });
          }
        }
        break;

      case 'response_end':
        debugLog('ChatWS', `response_end ${data.full_text ? data.full_text.length + ' chars' : 'empty'}`);
        if (data.full_text) {
          const msgs = [...this._state.messages];
          const last = msgs[msgs.length - 1];
          if (last?.role === 'assistant') {
            msgs[msgs.length - 1] = { ...last, content: data.full_text };
            this.setState({ messages: msgs });
          }
        }
        this.setState({ isStreaming: false });
        break;

      case 'session_reset':
        this.setState({ messages: [], pinnedIds: [] });
        break;

      case 'error':
        this.setState({
          isStreaming: false,
          messages: [
            ...this._state.messages,
            { role: 'assistant', content: `Error: ${data.message}` },
          ],
        });
        break;
    }
  }

  private startPolling() {
    this.clearPollTimer();
    this.pollTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'check_generating' }));
      } else {
        this.clearPollTimer();
      }
    }, 2000);
  }

  private clearPollTimer() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private clearRetryTimer() {
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
  }

  private setState(partial: Partial<ChatState>) {
    this._state = { ...this._state, ...partial };
    for (const fn of this.listeners) {
      fn();
    }
  }
}

// ── Singleton instance ─────────────────────────────────────────────────────

export const chatManager = new ChatManager();

// ── React hook ─────────────────────────────────────────────────────────────

import { useSyncExternalStore } from 'react';

export function useChatStore(): Readonly<ChatState> {
  return useSyncExternalStore(
    (cb) => chatManager.subscribe(cb),
    () => chatManager.state,
  );
}
