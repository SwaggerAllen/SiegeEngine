import { useEffect, Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from './store/authStore';
import { ErrorBoundary } from './components/ErrorBoundary';
import { LoginPage } from './pages/LoginPage';
import { ProjectListPage } from './pages/ProjectListPage';
import { ProjectCreatePage } from './pages/ProjectCreatePage';
import { ProjectDashboardLayout } from './pages/ProjectDashboardLayout';
import { GitHubCallbackPage } from './pages/GitHubCallbackPage';
import { DocumentsTab } from './components/tabs/DocumentsTab';
import { PipelineTab } from './components/tabs/PipelineTab';
import { TabSkeleton } from './components/DashboardSkeleton';
import { DebugOverlay } from './components/DebugOverlay';
// DebugOverlay: floating mini-panel for doom-loop scenarios where /debug is unreachable

// Lazy-loaded tabs (infrequently accessed)
const PromptsTab = lazy(() => import('./components/tabs/PromptsTab'));
const InputDocsTab = lazy(() => import('./components/tabs/InputDocsTab'));
const ChatTab = lazy(() => import('./components/tabs/ChatTab'));
const SettingsTab = lazy(() => import('./components/tabs/SettingsTab'));
const HistoryTab = lazy(() => import('./components/tabs/HistoryTab'));
const LogsTab = lazy(() => import('./components/tabs/LogsTab'));
const DebugTab = lazy(() => import('./components/tabs/DebugTab'));

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
    <DebugOverlay />
    <BrowserRouter>
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
