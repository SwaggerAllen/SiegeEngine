import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReferenceListResponse } from '../api/references';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ReferencesList } from './ReferencesList';

vi.mock('../api/references', async () => {
  const actual = await vi.importActual<typeof import('../api/references')>(
    '../api/references',
  );
  return {
    ...actual,
    getReferences: vi.fn(),
    getReference: vi.fn(),
    createReference: vi.fn(),
    updateReference: vi.fn(),
    approveReferenceDraft: vi.fn(),
    discardReferenceDraft: vi.fn(),
    deleteReference: vi.fn(),
    addReferenceEdge: vi.fn(),
    removeReferenceEdge: vi.fn(),
  };
});

import * as refsApi from '../api/references';

const mockedGet = refsApi.getReferences as unknown as ReturnType<typeof vi.fn>;

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
    mockedGet.mockResolvedValue(response());
    renderList();
    await waitFor(() =>
      expect(screen.getByText(/No references defined yet/i)).toBeInTheDocument(),
    );
  });

  it('renders a list item for each reference', async () => {
    mockedGet.mockResolvedValue(
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
    mockedGet.mockResolvedValue(response());
    renderList();
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /Add reference/i }),
      ).toBeInTheDocument(),
    );
  });
});
