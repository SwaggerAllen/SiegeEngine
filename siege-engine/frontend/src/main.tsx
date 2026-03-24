import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import App from './App';
import { queryClient } from './lib/queryClient';
import { useErrorLogStore } from './store/errorLogStore';
import { debugLog, debugError } from './lib/debugLog';
import './index.css';

// Mark the start of each page session in the debug log so localStorage entries
// from previous page loads are visually separated from the current session.
debugLog('page', `LOAD url=${window.location.pathname}`);

// Safety net: prevent stray unhandled rejections from crashing Safari.
// All fire-and-forget promises SHOULD have .catch() handlers, but this
// catches anything that slips through (e.g. third-party libraries).
window.addEventListener('unhandledrejection', (event) => {
  console.error('[Unhandled Rejection]', event.reason);
  debugError('unhandledrejection', event.reason);
  useErrorLogStore.getState().pushError('unhandledrejection', event.reason);
  event.preventDefault(); // Prevents Safari from terminating the page
});

window.addEventListener('error', (event) => {
  console.error('[Global Error]', event.error || event.message);
  debugError('window.error', event.error || event.message);
  useErrorLogStore.getState().pushError('window.onerror', event.error || event.message);
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  </StrictMode>
);
