import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReferenceListResponse } from '../api/references';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ReferencesList } from './ReferencesList';

const apiStub: {
  list: ReturnType<typeof vi.fn>;
  getDetail: ReturnType<typeof vi.fn>;
} = {
  list: vi.fn(),
  getDetail: vi.fn(),
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
    expect(screen.getByText(/not yet populated/i)).toBeInTheDocument();
  });

  it('points users at the /create_ref skill', async () => {
    apiStub.list.mockResolvedValue(response());
    renderList();
    await waitFor(() =>
      expect(screen.getByText(/\/create_ref/)).toBeInTheDocument(),
    );
  });
});
