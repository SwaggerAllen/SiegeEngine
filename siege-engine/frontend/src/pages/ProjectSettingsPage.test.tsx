import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ProjectSettingsPage } from './ProjectSettingsPage';

vi.mock('../api/projectSettings', async (importOriginal) => {
  // Keep the real schema, defaults, and NODE_COUNT_RANGE_FIELDS
  // metadata intact; only stub the two API fetchers.
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
import {
  DEFAULT_FEATURES_PER_GROUP,
  DEFAULT_SUBCOMPONENTS_PER_COMPONENT,
  DEFAULT_SUBRESPONSIBILITIES_PER_COMPONENT,
  DEFAULT_TOP_LEVEL_COMPONENTS,
  DEFAULT_TOP_LEVEL_RESPONSIBILITIES,
  type ProjectSettings,
} from '../api/projectSettings';

// Helper: build a fully-populated ProjectSettings for mocking the
// GET response. The schema defaults handle omitted NodeCountRange
// fields, but the PUT flow requires a complete payload so tests
// that assert `toHaveBeenCalledWith(...)` want an explicit object.
function defaultSettings(overrides?: Partial<ProjectSettings>): ProjectSettings {
  return {
    generation_timeout_seconds: 900,
    features_per_group: DEFAULT_FEATURES_PER_GROUP,
    top_level_responsibilities: DEFAULT_TOP_LEVEL_RESPONSIBILITIES,
    top_level_components: DEFAULT_TOP_LEVEL_COMPONENTS,
    subcomponents_per_component: DEFAULT_SUBCOMPONENTS_PER_COMPONENT,
    subresponsibilities_per_component: DEFAULT_SUBRESPONSIBILITIES_PER_COMPONENT,
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

  it('renders five NodeCountRange sub-forms with their defaults', async () => {
    mockedGet.mockResolvedValue(defaultSettings());
    renderPage();
    // Each sub-form is identified by its label heading. The
    // individual number inputs are disambiguated by id
    // (e.g. `top_level_components-floor`) rather than by label
    // text, because every sub-form reuses "Floor"/"Typical
    // min"/etc. internally.
    await screen.findByText('Features per group');
    expect(screen.getByText('Top-level responsibilities')).toBeInTheDocument();
    expect(screen.getByText('Top-level components')).toBeInTheDocument();
    expect(screen.getByText('Subcomponents per component')).toBeInTheDocument();
    expect(screen.getByText('Subresponsibilities per component')).toBeInTheDocument();

    // Spot-check the default numbers on one of the sub-forms.
    const floor = document.getElementById('top_level_components-floor') as HTMLInputElement;
    const typMax = document.getElementById('top_level_components-typical_max') as HTMLInputElement;
    const ceiling = document.getElementById('top_level_components-ceiling') as HTMLInputElement;
    expect(floor.value).toBe('3');
    expect(typMax.value).toBe('15');
    expect(ceiling.value).toBe('25');
  });

  it('blocks save when a NodeCountRange ordering is violated', async () => {
    mockedGet.mockResolvedValue(defaultSettings());
    renderPage();
    await screen.findByText('Top-level components');
    const floor = document.getElementById('top_level_components-floor') as HTMLInputElement;
    // Push floor above typical_min (default 5) — ordering invariant fails.
    fireEvent.change(floor, { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: /Save/i }));
    await waitFor(() =>
      expect(screen.getByText(/Values must be ordered/i)).toBeInTheDocument()
    );
    expect(mockedUpdate).not.toHaveBeenCalled();
  });

  it('submits updated NodeCountRange values alongside the timeout', async () => {
    mockedGet.mockResolvedValue(defaultSettings());
    mockedUpdate.mockResolvedValue(defaultSettings());
    renderPage();
    await screen.findByText('Top-level components');
    const typMax = document.getElementById('top_level_components-typical_max') as HTMLInputElement;
    fireEvent.change(typMax, { target: { value: '18' } });
    fireEvent.click(screen.getByRole('button', { name: /Save/i }));
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalled());
    const call = mockedUpdate.mock.calls[0];
    expect(call[0]).toBe('proj_1');
    expect(call[1].top_level_components.typical_max).toBe(18);
    expect(call[1].top_level_components.ceiling).toBe(25);
    // Other tiers unchanged.
    expect(call[1].features_per_group).toEqual(DEFAULT_FEATURES_PER_GROUP);
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
    fireEvent.change(input, { target: { value: '120' } });
    fireEvent.click(screen.getByRole('button', { name: /Save/i }));
    await waitFor(() =>
      expect(screen.getByText(/^Timeout must be between 1 and 60 minutes/)).toBeInTheDocument()
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
