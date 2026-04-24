import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ProjectSettingsPage } from './ProjectSettingsPage';

vi.mock('../api/projectSettings', async (importOriginal) => {
  // Keep the real schema intact; only stub the two API fetchers.
  const actual =
    await importOriginal<typeof import('../api/projectSettings')>();
  return {
    ...actual,
    getProjectSettings: vi.fn(),
    updateProjectSettings: vi.fn(),
  };
});

vi.mock('../api/projects', () => ({
  getProject: vi.fn(),
}));

import * as settingsApi from '../api/projectSettings';
import * as projectsApi from '../api/projects';
import { type ProjectSettings } from '../api/projectSettings';

function defaultSettings(overrides?: Partial<ProjectSettings>): ProjectSettings {
  return {
    generation_timeout_seconds: 900,
    cli_max_budget_usd: 2.0,
    ...overrides,
  };
}

const mockedGet = settingsApi.getProjectSettings as unknown as ReturnType<typeof vi.fn>;
const mockedUpdate = settingsApi.updateProjectSettings as unknown as ReturnType<
  typeof vi.fn
>;
const mockedGetProject = projectsApi.getProject as unknown as ReturnType<typeof vi.fn>;

function renderPage() {
  return render(
    <TestQueryWrapper>
      <MemoryRouter initialEntries={['/projects/proj_1/settings']}>
        <Routes>
          <Route path="/projects/:id/settings" element={<ProjectSettingsPage />} />
        </Routes>
      </MemoryRouter>
    </TestQueryWrapper>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedGetProject.mockResolvedValue({
    id: 'proj_1',
    name: 'My Project',
    description: null,
    remote_url: null,
    github_repo_slug: null,
    auto_push_enabled: false,
    git_repo_path: '/tmp/p',
    created_at: '2026-04-13T00:00:00',
    updated_at: '2026-04-13T00:00:00',
  });
});

describe('ProjectSettingsPage', () => {
  it('loads the current timeout converted to minutes', async () => {
    mockedGet.mockResolvedValue(defaultSettings());
    renderPage();
    const input = (await screen.findByLabelText(/Generation timeout/i)) as HTMLInputElement;
    expect(input.value).toBe('15');
  });

  it('converts minutes back to seconds when saving', async () => {
    mockedGet.mockResolvedValue(defaultSettings());
    mockedUpdate.mockResolvedValue(defaultSettings({ generation_timeout_seconds: 1200 }));
    renderPage();
    const input = (await screen.findByLabelText(/Generation timeout/i)) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: /Save/i }));
    await waitFor(() =>
      expect(mockedUpdate).toHaveBeenCalledWith(
        'proj_1',
        defaultSettings({ generation_timeout_seconds: 1200 })
      )
    );
    await waitFor(() => expect(screen.getByText(/Saved\./i)).toBeInTheDocument());
  });

  it('rejects a value outside the allowed range client-side', async () => {
    mockedGet.mockResolvedValue(defaultSettings());
    renderPage();
    const input = (await screen.findByLabelText(/Generation timeout/i)) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: /Save/i }));
    await waitFor(() =>
      expect(screen.getByText(/must be a positive number/i)).toBeInTheDocument()
    );
    expect(mockedUpdate).not.toHaveBeenCalled();
  });

  it('rejects a value above the maximum', async () => {
    mockedGet.mockResolvedValue(defaultSettings());
    renderPage();
    const input = (await screen.findByLabelText(/Generation timeout/i)) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '500' } });
    fireEvent.click(screen.getByRole('button', { name: /Save/i }));
    await waitFor(() =>
      expect(screen.getByText(/^Timeout must be between 1 and 240 minutes/)).toBeInTheDocument()
    );
    expect(mockedUpdate).not.toHaveBeenCalled();
  });

  it('shows the project name in the header', async () => {
    mockedGet.mockResolvedValue(defaultSettings());
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/My Project — Settings/i)).toBeInTheDocument()
    );
  });
});
