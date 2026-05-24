import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ProjectCreatePage } from './ProjectCreatePage';

vi.mock('../api/projects', () => ({
  createProject: vi.fn(),
  createSampleProject: vi.fn(),
}));

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => vi.fn() };
});

import * as projectsApi from '../api/projects';

const mockedCreate = projectsApi.createProject as unknown as ReturnType<typeof vi.fn>;
const mockedSample = projectsApi.createSampleProject as unknown as ReturnType<typeof vi.fn>;

function renderPage() {
  return render(
    <TestQueryWrapper>
      <MemoryRouter>
        <ProjectCreatePage />
      </MemoryRouter>
    </TestQueryWrapper>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ProjectCreatePage', () => {
  it('renders the GitHub-URL + project-doc fields by default', () => {
    renderPage();
    expect(screen.getByPlaceholderText(/github\.com\/owner\/repo/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Project Document/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Use the built-in sample/i)).not.toBeChecked();
  });

  it('hides the URL + project-doc fields once the sample checkbox is ticked', () => {
    renderPage();
    fireEvent.click(screen.getByLabelText(/Use the built-in sample/i));
    expect(screen.queryByPlaceholderText(/github\.com\/owner\/repo/i)).toBeNull();
    expect(screen.queryByLabelText(/Project Document/i)).toBeNull();
  });

  it('submitting with sample checked calls createSampleProject', async () => {
    mockedSample.mockResolvedValue({
      id: 'proj_sample',
      name: 'Sample',
      description: null,
      git_repo_path: '/tmp/sample',
      source: 'upload',
      created_at: '2026-05-24T00:00:00',
      updated_at: '2026-05-24T00:00:00',
    });
    renderPage();
    fireEvent.click(screen.getByLabelText(/Use the built-in sample/i));
    fireEvent.change(screen.getByLabelText(/Project Name/i), {
      target: { value: 'Sample' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Create Sample Project/i }));

    await waitFor(() => {
      expect(mockedSample).toHaveBeenCalledTimes(1);
    });
    expect(mockedSample).toHaveBeenCalledWith('Sample', null);
    expect(mockedCreate).not.toHaveBeenCalled();
  });

  it('submitting without sample still uses the original create flow', async () => {
    mockedCreate.mockResolvedValue({
      id: 'proj_normal',
      name: 'Normal',
      description: null,
      git_repo_path: '/tmp/normal',
      source: 'remote',
      created_at: '2026-05-24T00:00:00',
      updated_at: '2026-05-24T00:00:00',
    });
    renderPage();
    fireEvent.change(screen.getByLabelText(/Project Name/i), {
      target: { value: 'Normal' },
    });
    fireEvent.change(screen.getByLabelText(/Project Document/i), {
      target: { value: '# Doc' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Create Project/i }));

    await waitFor(() => {
      expect(mockedCreate).toHaveBeenCalledTimes(1);
    });
    expect(mockedSample).not.toHaveBeenCalled();
  });
});
