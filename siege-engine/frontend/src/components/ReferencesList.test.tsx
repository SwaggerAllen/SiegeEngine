import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReferenceListResponse } from '../api/references';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ReferencesList } from './ReferencesList';

// The component pulls everything off makeReferencesApi(projectId).
// Mock the factory so each call returns a stable stub object the
// tests can configure via `apiStub`.
const apiStub: {
  list: ReturnType<typeof vi.fn>;
  getDetail: ReturnType<typeof vi.fn>;
  create: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
  addEdge: ReturnType<typeof vi.fn>;
  removeEdge: ReturnType<typeof vi.fn>;
  getState: ReturnType<typeof vi.fn>;
  postFeedback: ReturnType<typeof vi.fn>;
  approveDraft: ReturnType<typeof vi.fn>;
  discardDraft: ReturnType<typeof vi.fn>;
  cancelGeneration: ReturnType<typeof vi.fn>;
  resetTier: ReturnType<typeof vi.fn>;
  getPromptPreview: ReturnType<typeof vi.fn>;
} = {
  list: vi.fn(),
  getDetail: vi.fn(),
  create: vi.fn(),
  delete: vi.fn(),
  addEdge: vi.fn(),
  removeEdge: vi.fn(),
  getState: vi.fn(),
  postFeedback: vi.fn(),
  approveDraft: vi.fn(),
  discardDraft: vi.fn(),
  cancelGeneration: vi.fn(),
  resetTier: vi.fn(),
  getPromptPreview: vi.fn(),
};

vi.mock('../api/references', async () => {
  const actual = await vi.importActual<typeof import('../api/references')>(
    '../api/references',
  );
  return {
    ...actual,
    makeReferencesApi: vi.fn(() => apiStub),
  };
});

function renderList() {
  return render(
    <TestQueryWrapper>
      <ReferencesList projectId="proj_1" />
    </TestQueryWrapper>,
  );
}

function response(
  overrides: Partial<ReferenceListResponse> = {},
): ReferenceListResponse {
  return {
    references: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ReferencesList', () => {
  it('shows the empty state when no refs exist', async () => {
    apiStub.list.mockResolvedValue(response());
    renderList();
    await waitFor(() =>
      expect(screen.getByText(/No references defined yet/i)).toBeInTheDocument(),
    );
  });

  it('renders a list item for each reference', async () => {
    apiStub.list.mockResolvedValue(
      response({
        references: [
          {
            id: 'ref_AAAAAAAA',
            name: 'Deployment Runbook',
            has_content: true,
            updated_at: '2026-04-16T00:00:00',
          },
          {
            id: 'ref_BBBBBBBB',
            name: 'DSL Spec',
            has_content: false,
            updated_at: '2026-04-16T00:00:00',
          },
        ],
      }),
    );
    renderList();
    await waitFor(() =>
      expect(screen.getByText('Deployment Runbook')).toBeInTheDocument(),
    );
    expect(screen.getByText('DSL Spec')).toBeInTheDocument();
    expect(screen.getByText(/not yet approved/i)).toBeInTheDocument();
  });

  it('shows an "+ Add reference" button', async () => {
    apiStub.list.mockResolvedValue(response());
    renderList();
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /Add reference/i }),
      ).toBeInTheDocument(),
    );
  });
});
