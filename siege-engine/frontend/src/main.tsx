import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './index.css';

// Safety net: prevent stray unhandled rejections from crashing Safari.
// All fire-and-forget promises SHOULD have .catch() handlers, but this
// catches anything that slips through (e.g. third-party libraries).
window.addEventListener('unhandledrejection', (event) => {
  console.error('[Unhandled Rejection]', event.reason);
  event.preventDefault(); // Prevents Safari from terminating the page
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
