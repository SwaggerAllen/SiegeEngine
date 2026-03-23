import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
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
