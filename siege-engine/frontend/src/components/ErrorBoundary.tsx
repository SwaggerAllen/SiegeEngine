import { Component, type ReactNode } from 'react';
import { useErrorLogStore } from '../store/errorLogStore';
import { debugError } from '../lib/debugLog';

interface Props {
  children: ReactNode;
  /** Optional fallback label shown instead of full-page error. */
  fallbackLabel?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary] Caught render error:', error, info.componentStack);
    debugError('ErrorBoundary', error);
    debugError('ErrorBoundary.stack', info.componentStack ?? 'no component stack');
    useErrorLogStore.getState().pushError('ErrorBoundary', error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-screen bg-gray-900 text-white gap-4 p-8">
          <h1 className="text-xl font-bold text-red-400">Something went wrong</h1>
          <pre className="text-sm text-gray-400 max-w-lg whitespace-pre-wrap break-words bg-gray-800 rounded p-4">
            {this.state.error?.message || 'Unknown error'}
          </pre>
          <button
            onClick={() => {
              this.setState({ hasError: false, error: null });
              window.location.reload();
            }}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded text-sm"
          >
            Reload Page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

/** Max crashes before circuit breaker locks the panel in error state. */
const CIRCUIT_BREAKER_LIMIT = 3;
/** Reset the crash counter after this many ms of stability. */
const CIRCUIT_BREAKER_RESET_MS = 30_000;

interface PanelState {
  hasError: boolean;
  error: Error | null;
  /** Number of times this boundary has caught an error since last reset. */
  crashCount: number;
  /** Whether the circuit breaker has tripped (too many crashes). */
  tripped: boolean;
}

/**
 * Lightweight error boundary for individual panels/sections.
 * Recovers in-place without requiring a full page reload.
 *
 * Includes a circuit breaker: if the panel crashes 3+ times within 30s,
 * the Retry button is replaced with a "locked" state that requires a
 * page reload — preventing crash loops.
 */
export class PanelErrorBoundary extends Component<Props, PanelState> {
  state: PanelState = { hasError: false, error: null, crashCount: 0, tripped: false };
  private resetTimer: ReturnType<typeof setTimeout> | null = null;

  static getDerivedStateFromError(error: Error): Partial<PanelState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[PanelErrorBoundary] Caught render error:', error, info.componentStack);
    debugError(`PanelEB(${this.props.fallbackLabel || 'panel'})`, error);
    debugError(`PanelEB(${this.props.fallbackLabel || 'panel'}).stack`, info.componentStack ?? 'no component stack');
    useErrorLogStore.getState().pushError(
      `PanelErrorBoundary(${this.props.fallbackLabel || 'panel'})`,
      error,
    );

    this.setState((prev) => {
      const crashCount = prev.crashCount + 1;
      const tripped = crashCount >= CIRCUIT_BREAKER_LIMIT;
      if (tripped) {
        console.warn(`[PanelErrorBoundary] Circuit breaker tripped for "${this.props.fallbackLabel}" after ${crashCount} crashes`);
      }
      return { crashCount, tripped };
    });

    // Reset crash counter after a period of stability
    if (this.resetTimer) clearTimeout(this.resetTimer);
    this.resetTimer = setTimeout(() => {
      this.setState({ crashCount: 0, tripped: false });
    }, CIRCUIT_BREAKER_RESET_MS);
  }

  componentWillUnmount() {
    if (this.resetTimer) clearTimeout(this.resetTimer);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center p-4 text-gray-400 gap-2">
          <p className="text-sm text-red-400">
            {this.props.fallbackLabel || 'This panel encountered an error'}
          </p>
          <pre className="text-xs text-gray-500 max-w-md truncate">
            {this.state.error?.message}
          </pre>
          {this.state.tripped ? (
            <p className="text-xs text-yellow-500">
              Panel crashed {this.state.crashCount} times — retry disabled.
              Reload the page to try again.
            </p>
          ) : (
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-white rounded text-xs"
            >
              Retry
            </button>
          )}
        </div>
      );
    }
    return this.props.children;
  }
}
