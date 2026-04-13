import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ComponentList } from './ComponentList';
import type { ComponentListResponse } from '../api/sysarch';

vi.mock('../api/sysarch', () => ({
  getComponents: vi.fn(),
}));

import * as sysarchApi from '../api/sysarch';

const mockedGet = sysarchApi.getComponents as unknown as ReturnType<typeof vi.fn>;

function renderList(mintPending: boolean = false) {
  return render(
    <TestQueryWrapper>
      <ComponentList projectId="proj_1" mintPending={mintPending} />
    </TestQueryWrapper>
  );
}

function makeResponse(
  comps: Array<{ id: string; name: string; kind: string; display_order: number }> = []
): ComponentListResponse {
  return {
    components: comps.map((c) => ({ ...c, updated_at: '2026-04-13T00:00:00' })),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ComponentList', () => {
  it('shows loading state initially', async () => {
    mockedGet.mockImplementation(() => new Promise(() => {}));
    renderList();
    await waitFor(() =>
      expect(screen.getByText(/Loading components/i)).toBeInTheDocument()
    );
  });

  it('shows empty state when no components and not mint-pending', async () => {
    mockedGet.mockResolvedValue(makeResponse([]));
    renderList(false);
    await waitFor(() =>
      expect(screen.getByText(/No components yet/i)).toBeInTheDocument()
    );
  });

  it('shows minting indicator when empty and mint-pending', async () => {
    mockedGet.mockResolvedValue(makeResponse([]));
    renderList(true);
    await waitFor(() =>
      expect(
        screen.getByText(/Minting components from the approved system architecture/i)
      ).toBeInTheDocument()
    );
  });

  it('renders cards with name, kind badge, and id', async () => {
    mockedGet.mockResolvedValue(
      makeResponse([
        { id: 'comp_auth01', name: 'Authentication', kind: 'domain', display_order: 0 },
        { id: 'comp_ui0001', name: 'Dashboard', kind: 'presentational', display_order: 1 },
      ])
    );
    renderList(false);

    await waitFor(() => expect(screen.getByText('Authentication')).toBeInTheDocument());
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getAllByText(/^domain$/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^presentational$/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Top-level Components \(2\)/)).toBeInTheDocument();
    expect(screen.getByText('comp_auth01')).toBeInTheDocument();
    expect(screen.getByText('comp_ui0001')).toBeInTheDocument();
  });

  it('shows display order badges', async () => {
    mockedGet.mockResolvedValue(
      makeResponse([
        { id: 'comp_a', name: 'First', kind: 'domain', display_order: 0 },
        { id: 'comp_b', name: 'Second', kind: 'domain', display_order: 1 },
      ])
    );
    renderList(false);
    await waitFor(() => expect(screen.getByText('First')).toBeInTheDocument());
    expect(screen.getByText('#0')).toBeInTheDocument();
    expect(screen.getByText('#1')).toBeInTheDocument();
  });
});
