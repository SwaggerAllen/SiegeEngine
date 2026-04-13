import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ResponsibilityList } from './ResponsibilityList';
import type { ResponsibilityListResponse } from '../api/requirements';

vi.mock('../api/requirements', () => ({
  getResponsibilities: vi.fn(),
}));

import * as reqsApi from '../api/requirements';

const mockedGet = reqsApi.getResponsibilities as unknown as ReturnType<typeof vi.fn>;

function renderList(mintPending: boolean = false) {
  return render(
    <TestQueryWrapper>
      <ResponsibilityList projectId="proj_1" mintPending={mintPending} />
    </TestQueryWrapper>
  );
}

function makeResponse(
  resps: Array<{ id: string; name: string; content: string; display_order: number }> = []
): ResponsibilityListResponse {
  return {
    responsibilities: resps.map((r) => ({
      ...r,
      updated_at: '2026-04-13T00:00:00',
    })),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ResponsibilityList', () => {
  it('shows loading state initially', async () => {
    mockedGet.mockImplementation(() => new Promise(() => {}));
    renderList();
    await waitFor(() =>
      expect(screen.getByText(/Loading responsibilities/i)).toBeInTheDocument()
    );
  });

  it('shows empty state when no responsibilities and mint not pending', async () => {
    mockedGet.mockResolvedValue(makeResponse([]));
    renderList(false);
    await waitFor(() =>
      expect(screen.getByText(/No responsibilities yet/i)).toBeInTheDocument()
    );
  });

  it('shows minting indicator when empty and mint pending', async () => {
    mockedGet.mockResolvedValue(makeResponse([]));
    renderList(true);
    await waitFor(() =>
      expect(
        screen.getByText(/Minting responsibilities from the approved requirements/i)
      ).toBeInTheDocument()
    );
  });

  it('renders responsibility cards when present', async () => {
    mockedGet.mockResolvedValue(
      makeResponse([
        {
          id: 'resp_1',
          name: 'User Authentication',
          content: 'Identify callers and establish sessions.',
          display_order: 0,
        },
        {
          id: 'resp_2',
          name: 'Billing',
          content: 'Bill accounts and manage plans.',
          display_order: 1,
        },
      ])
    );
    renderList(false);

    await waitFor(() =>
      expect(screen.getByText('User Authentication')).toBeInTheDocument()
    );
    expect(screen.getByText('Billing')).toBeInTheDocument();
    expect(
      screen.getByText(/Identify callers and establish sessions/)
    ).toBeInTheDocument();
    expect(screen.getByText(/Bill accounts and manage plans/)).toBeInTheDocument();
    expect(screen.getByText(/Top-level Responsibilities \(2\)/)).toBeInTheDocument();
  });

  it('shows display_order badge on each responsibility', async () => {
    mockedGet.mockResolvedValue(
      makeResponse([
        { id: 'r1', name: 'First', content: 'a', display_order: 0 },
        { id: 'r2', name: 'Second', content: 'b', display_order: 1 },
      ])
    );
    renderList(false);
    await waitFor(() => expect(screen.getByText('First')).toBeInTheDocument());
    expect(screen.getByText('#0')).toBeInTheDocument();
    expect(screen.getByText('#1')).toBeInTheDocument();
  });

  it('shows error state when the query fails', async () => {
    mockedGet.mockRejectedValue({
      response: { status: 500, data: { detail: 'database offline' } },
    });
    renderList(false);
    await waitFor(() =>
      expect(screen.getByText(/database offline/i)).toBeInTheDocument()
    );
  });
});
