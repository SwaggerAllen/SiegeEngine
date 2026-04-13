import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { SubresponsibilityList } from './SubresponsibilityList';
import type { SubresponsibilityListResponse } from '../api/subreqs';

vi.mock('../api/subreqs', () => ({
  getSubresponsibilities: vi.fn(),
}));

import * as subreqsApi from '../api/subreqs';

const mockedGet = subreqsApi.getSubresponsibilities as unknown as ReturnType<typeof vi.fn>;

function renderList(mintPending = false) {
  return render(
    <TestQueryWrapper>
      <SubresponsibilityList
        projectId="proj_1"
        componentId="comp_billing"
        mintPending={mintPending}
      />
    </TestQueryWrapper>
  );
}

function makeResponse(
  items: Array<{ id: string; name: string; content: string; display_order: number }> = []
): SubresponsibilityListResponse {
  return {
    subresponsibilities: items.map((i) => ({ ...i, updated_at: '2026-04-13T00:00:00' })),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SubresponsibilityList', () => {
  it('shows loading state initially', async () => {
    mockedGet.mockImplementation(() => new Promise(() => {}));
    renderList();
    await waitFor(() =>
      expect(screen.getByText(/Loading subresponsibilities/i)).toBeInTheDocument()
    );
  });

  it('shows empty state', async () => {
    mockedGet.mockResolvedValue(makeResponse([]));
    renderList(false);
    await waitFor(() =>
      expect(screen.getByText(/No subresponsibilities yet/i)).toBeInTheDocument()
    );
  });

  it('shows minting indicator when mint-pending', async () => {
    mockedGet.mockResolvedValue(makeResponse([]));
    renderList(true);
    await waitFor(() =>
      expect(screen.getByText(/Minting subresponsibilities/i)).toBeInTheDocument()
    );
  });

  it('renders subresponsibility cards', async () => {
    mockedGet.mockResolvedValue(
      makeResponse([
        {
          id: 'resp_token01',
          name: 'Card Tokenization',
          content: 'Convert raw cards.',
          display_order: 0,
        },
        {
          id: 'resp_retry02',
          name: 'Retry Scheduling',
          content: 'Backoff retries.',
          display_order: 1,
        },
      ])
    );
    renderList(false);
    await waitFor(() =>
      expect(screen.getByText('Card Tokenization')).toBeInTheDocument()
    );
    expect(screen.getByText('Retry Scheduling')).toBeInTheDocument();
    expect(screen.getByText(/Convert raw cards/)).toBeInTheDocument();
    expect(screen.getByText(/Backoff retries/)).toBeInTheDocument();
    expect(screen.getByText(/Subresponsibilities \(2\)/)).toBeInTheDocument();
    expect(screen.getByText('resp_token01')).toBeInTheDocument();
  });
});
