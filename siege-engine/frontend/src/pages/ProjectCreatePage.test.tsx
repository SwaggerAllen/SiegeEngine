import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ProjectCreatePage } from './ProjectCreatePage';

vi.mock('../api/projects', () => ({
  createProject: vi.fn(),
  importProject: vi.fn(),
}));

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => vi.fn() };
});

import * as projectsApi from '../api/projects';

const mockedCreate = projectsApi.createProject as unknown as ReturnType<typeof vi.fn>;
const mockedImport = projectsApi.importProject as unknown as ReturnType<typeof vi.fn>;

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

describe('ProjectCreatePage mode toggle', () => {
  it('starts in GitHub URL mode with the project-doc textarea visible', () => {
    renderPage();
    // The URL input is present, the file input is not.
    expect(screen.getByPlaceholderText(/github\.com\/owner\/repo/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Project Document/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Project archive/i)).toBeNull();
  });

  it('toggling to Upload artifacts swaps the URL + project-doc for a file picker', () => {
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: /Upload artifacts/i }));
    // File picker is now visible; URL + project-doc fields are gone.
    expect(screen.getByLabelText(/Project archive/i)).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/github\.com\/owner\/repo/i)).toBeNull();
    expect(screen.queryByLabelText(/Project Document/i)).toBeNull();
  });

  it('submitting in upload mode calls importProject with the chosen file', async () => {
    mockedImport.mockResolvedValue({
      id: 'proj_imported',
      name: 'Imported',
      description: null,
      git_repo_path: '/tmp/imported',
      source: 'upload',
      created_at: '2026-05-24T00:00:00',
      updated_at: '2026-05-24T00:00:00',
    });
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: /Upload artifacts/i }));

    fireEvent.change(screen.getByLabelText(/Project Name/i), {
      target: { value: 'Imported' },
    });
    const tarball = new File([new Uint8Array(16)], 'sample.tar.gz', {
      type: 'application/gzip',
    });
    fireEvent.change(screen.getByLabelText(/Project archive/i), {
      target: { files: [tarball] },
    });
    fireEvent.click(screen.getByRole('button', { name: /Import Project/i }));

    await waitFor(() => {
      expect(mockedImport).toHaveBeenCalledTimes(1);
    });
    expect(mockedImport.mock.calls[0][0]).toBe('Imported');
    expect(mockedImport.mock.calls[0][2]).toBe(tarball);
    expect(mockedCreate).not.toHaveBeenCalled();
  });

  it('rejects an upload-mode submit with no file selected', () => {
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: /Upload artifacts/i }));
    fireEvent.change(screen.getByLabelText(/Project Name/i), {
      target: { value: 'Imported' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Import Project/i }));
    expect(screen.getByText(/Choose a tarball or zip/i)).toBeInTheDocument();
    expect(mockedImport).not.toHaveBeenCalled();
  });
});
