import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { TestQueryWrapper } from '../test/queryWrapper';
import { SubcomponentList } from './SubcomponentList';
import type { SubcomponentListResponse } from '../api/comparch';

vi.mock('../api/comparch', async () => {
  const actual = await vi.importActual<typeof import('../api/comparch')>(
    '../api/comparch'
  );
  return {
    ...actual,
    getSubcomponents: vi.fn(),
  };
});

import * as comparchApi from '../api/comparch';

const mockedGet = comparchApi.getSubcomponents as unknown as ReturnType<
  typeof vi.fn
>;

function renderList(mintPending: boolean = false) {
  return render(
    <MemoryRouter>
      <TestQueryWrapper>
        <SubcomponentList
          projectId="proj_1"
          componentId="comp_billing1"
          mintPending={mintPending}
        />
      </TestQueryWrapper>
    </MemoryRouter>
  );
}

function makeResponse(
  subs: Array<{ id: string; name: string; display_order: number }> = []
): SubcomponentListResponse {
  return {
    subcomponents: subs.map((s) => ({
      ...s,
      parent_id: 'comp_billing1',
      updated_at: '2026-04-13T00:00:00',
    })),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SubcomponentList', () => {
  it('renders an empty state when mintPending is false', async () => {
    mockedGet.mockResolvedValue(makeResponse([]));
    renderList(false);
    await waitFor(() =>
      expect(screen.getByText(/does not decompose/i)).toBeInTheDocument()
    );
  });

  it('shows minting message when mintPending + empty list', async () => {
    mockedGet.mockResolvedValue(makeResponse([]));
    renderList(true);
    await waitFor(() =>
      expect(screen.getByText(/Minting subcomponents/i)).toBeInTheDocument()
    );
  });

  it('renders populated list with links to subcomparch pages', async () => {
    mockedGet.mockResolvedValue(
      makeResponse([
        { id: 'comp_token_sto', name: 'TokenStore', display_order: 0 },
        { id: 'comp_foundation', name: 'Foundation', display_order: 1 },
      ])
    );
    renderList(false);
    await waitFor(() => expect(screen.getByText('TokenStore')).toBeInTheDocument());
    expect(screen.getByText('Foundation')).toBeInTheDocument();

    // Each sub is rendered as a Link to the subcomparch page
    const tokenLink = screen.getByRole('link', { name: /TokenStore/ });
    expect(tokenLink).toHaveAttribute(
      'href',
      '/projects/proj_1/components/comp_billing1/subcomponents/comp_token_sto/subcomparch'
    );
    const foundationLink = screen.getByRole('link', { name: /Foundation/ });
    expect(foundationLink).toHaveAttribute(
      'href',
      '/projects/proj_1/components/comp_billing1/subcomponents/comp_foundation/subcomparch'
    );
    // "View subcomponent arch →" affordance
    expect(screen.getAllByText(/View subcomponent arch/i)).toHaveLength(2);
  });
});
