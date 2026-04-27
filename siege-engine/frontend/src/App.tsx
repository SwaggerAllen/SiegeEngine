import { useEffect, useRef } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from './store/authStore';
import { ErrorBoundary } from './components/ErrorBoundary';
import { QueueAnnounceRegion } from './components/QueueAnnounce';
import { debugLog } from './lib/debugLog';
import { LoginPage } from './pages/LoginPage';
import { ProjectListPage } from './pages/ProjectListPage';
import { ProjectCreatePage } from './pages/ProjectCreatePage';
import { ProjectWorkspacePage } from './pages/ProjectWorkspacePage';
import { ProjectSettingsPage } from './pages/ProjectSettingsPage';
import { ReviewBatchPage } from './pages/ReviewBatchPage';
import {
  RedirectComponentComparch,
  RedirectComponentFanIn,
  RedirectComponentImpl,
  RedirectSubcomponentImpl,
  RedirectSubcomponentSubcomparch,
  RedirectToSynthetic,
} from './pages/LegacyRedirects';
import { GitHubCallbackPage } from './pages/GitHubCallbackPage';

function NavigationLogger() {
  const location = useLocation();
  // Initialize to null so the first effect fire (on mount, and StrictMode's
  // simulated remount) is skipped rather than logged as a false "reload".
  const prev = useRef<string | null>(null);
  useEffect(() => {
    const from = prev.current;
    prev.current = location.pathname;
    if (from === null) return; // skip initial mount fire
    debugLog('nav', from === location.pathname
      ? `reload ${location.pathname}`
      : `${from} → ${location.pathname}`);
  }, [location]);
  return null;
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  const loadFromStorage = useAuthStore((s) => s.loadFromStorage);
  const checkTokenExpiry = useAuthStore((s) => s.checkTokenExpiry);

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
      <QueueAnnounceRegion />
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
              <ProjectWorkspacePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:id/settings"
          element={
            <ProtectedRoute>
              <ProjectSettingsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:id/review/:batchId"
          element={
            <ProtectedRoute>
              <ReviewBatchPage />
            </ProtectedRoute>
          }
        />
        {/* Legacy deep links — resolve to the workspace with the
            matching node selected. Bookmarks from the pre-workspace
            nav still land on the right place. */}
        <Route
          path="/projects/:id/components/:compId/comparch"
          element={
            <ProtectedRoute>
              <RedirectComponentComparch />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:id/components/:compId/subcomponents/:subId/subcomparch"
          element={
            <ProtectedRoute>
              <RedirectSubcomponentSubcomparch />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:id/components/:compId/impl"
          element={
            <ProtectedRoute>
              <RedirectComponentImpl />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:id/components/:compId/subcomponents/:subId/impl"
          element={
            <ProtectedRoute>
              <RedirectSubcomponentImpl />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:id/components/:compId/fanin"
          element={
            <ProtectedRoute>
              <RedirectComponentFanIn />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:id/decomposition"
          element={
            <ProtectedRoute>
              <RedirectToSynthetic target=":dag" />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:id/vocabulary"
          element={
            <ProtectedRoute>
              <RedirectToSynthetic target=":vocabulary" />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:id/references"
          element={
            <ProtectedRoute>
              <RedirectToSynthetic target=":references" />
            </ProtectedRoute>
          }
        />
        <Route path="/" element={<Navigate to="/projects" replace />} />
      </Routes>
    </BrowserRouter>
    </ErrorBoundary>
  );
}
