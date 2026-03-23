import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { useErrorLogStore } from './store/errorLogStore';
import './index.css';

// Safety net: prevent stray unhandled rejections from crashing Safari.
// All fire-and-forget promises SHOULD have .catch() handlers, but this
// catches anything that slips through (e.g. third-party libraries).
window.addEventListener('unhandledrejection', (event) => {
  console.error('[Unhandled Rejection]', event.reason);
  useErrorLogStore.getState().pushError('unhandledrejection', event.reason);
  event.preventDefault(); // Prevents Safari from terminating the page
});

window.addEventListener('error', (event) => {
  console.error('[Global Error]', event.error || event.message);
  useErrorLogStore.getState().pushError('window.onerror', event.error || event.message);
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
