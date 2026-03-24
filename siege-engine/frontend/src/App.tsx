import { useEffect, useRef, Suspense, lazy, type ComponentType } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from './store/authStore';
import { ErrorBoundary } from './components/ErrorBoundary';
import { debugLog } from './lib/debugLog';
import { LoginPage } from './pages/LoginPage';
import { ProjectListPage } from './pages/ProjectListPage';
import { ProjectCreatePage } from './pages/ProjectCreatePage';
import { ProjectDashboardLayout } from './pages/ProjectDashboardLayout';
import { GitHubCallbackPage } from './pages/GitHubCallbackPage';
import { DocumentsTab } from './components/tabs/DocumentsTab';
import { PipelineTab } from './components/tabs/PipelineTab';
import { TabSkeleton } from './components/DashboardSkeleton';

/**
 * Retry wrapper for React.lazy — if the dynamic import fails (e.g. Vite HMR
 * invalidated the chunk URL), retry once before giving up.
 */
function lazyRetry<T extends ComponentType<unknown>>(
  importFn: () => Promise<{ default: T }>,
) {
  return lazy(() =>
    importFn().catch(() => {
      // First attempt failed (stale chunk URL after HMR) — retry
      return importFn();
    }),
  );
}

// Lazy-loaded tabs (infrequently accessed)
const PromptsTab = lazyRetry(() => import('./components/tabs/PromptsTab'));
const InputDocsTab = lazyRetry(() => import('./components/tabs/InputDocsTab'));
const ChatTab = lazyRetry(() => import('./components/tabs/ChatTab'));
const SettingsTab = lazyRetry(() => import('./components/tabs/SettingsTab'));
const HistoryTab = lazyRetry(() => import('./components/tabs/HistoryTab'));
const LogsTab = lazyRetry(() => import('./components/tabs/LogsTab'));
const DebugTab = lazyRetry(() => import('./components/tabs/DebugTab'));

function NavigationLogger() {
  const location = useLocation();
  const prev = useRef(location.pathname);
  useEffect(() => {
    const from = prev.current;
    prev.current = location.pathname;
    debugLog('nav', from === location.pathname
      ? `reload ${location.pathname}`
      : `${from} → ${location.pathname}`);
  }, [location]);
  return null;
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuthStore();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function LazyTab({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<TabSkeleton />}>{children}</Suspense>;
}

export default function App() {
  const { loadFromStorage, checkTokenExpiry } = useAuthStore();

  useEffect(() => {
    loadFromStorage();
    // Check token expiry every 60 seconds
    const interval = setInterval(checkTokenExpiry, 60_000);
    return () => clearInterval(interval);
  }, [loadFromStorage, checkTokenExpiry]);

  return (
    <ErrorBoundary>
    <BrowserRouter>
      <NavigationLogger />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/github/callback" element={<GitHubCallbackPage />} />
        <Route
          path="/projects"
          element={
            <ProtectedRoute>
              <ProjectListPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/new"
          element={
            <ProtectedRoute>
              <ProjectCreatePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:id"
          element={
            <ProtectedRoute>
              <ProjectDashboardLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="documents" replace />} />
          <Route path="documents" element={<DocumentsTab />} />
          <Route path="pipeline" element={<PipelineTab />} />
          <Route path="prompts" element={<LazyTab><PromptsTab /></LazyTab>} />
          <Route path="input-docs" element={<LazyTab><InputDocsTab /></LazyTab>} />
          <Route path="chat" element={<LazyTab><ChatTab /></LazyTab>} />
          <Route path="settings" element={<LazyTab><SettingsTab /></LazyTab>} />
          <Route path="history" element={<LazyTab><HistoryTab /></LazyTab>} />
          <Route path="logs" element={<LazyTab><LogsTab /></LazyTab>} />
          <Route path="debug" element={<LazyTab><DebugTab /></LazyTab>} />
        </Route>
        <Route path="/" element={<Navigate to="/projects" replace />} />
      </Routes>
    </BrowserRouter>
    </ErrorBoundary>
  );
}
