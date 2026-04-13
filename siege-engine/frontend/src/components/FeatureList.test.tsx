import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { FeatureList } from './FeatureList';
import type { FeatureListResponse } from '../api/features';

// Mock the API module so we can drive component state from tests.
vi.mock('../api/features', () => ({
  getFeatures: vi.fn(),
}));

import * as featuresApi from '../api/features';

const mockedGet = featuresApi.getFeatures as unknown as ReturnType<typeof vi.fn>;

function renderList(mintPending: boolean = false) {
  return render(
    <TestQueryWrapper>
      <FeatureList projectId="proj_1" mintPending={mintPending} />
    </TestQueryWrapper>
  );
}

function makeResponse(
  features: Array<{
    id: string;
    name: string;
    content: string;
    display_order: number;
  }> = []
): FeatureListResponse {
  return {
    features: features.map((f) => ({
      ...f,
      updated_at: '2026-04-12T00:00:00',
    })),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FeatureList', () => {
  it('shows loading state initially', async () => {
    // Never-resolving promise keeps the query in loading state.
    mockedGet.mockImplementation(() => new Promise(() => {}));
    renderList();
    await waitFor(() => expect(screen.getByText(/Loading features/i)).toBeInTheDocument());
  });

  it('shows empty state when no features and mint not pending', async () => {
    mockedGet.mockResolvedValue(makeResponse([]));
    renderList(false);
    await waitFor(() => expect(screen.getByText(/No features yet/i)).toBeInTheDocument());
  });

  it('shows minting indicator when no features yet and mint is pending', async () => {
    mockedGet.mockResolvedValue(makeResponse([]));
    renderList(true);
    await waitFor(() =>
      expect(screen.getByText(/Minting features from the approved expansion/i)).toBeInTheDocument()
    );
  });

  it('renders feature cards when features are present', async () => {
    mockedGet.mockResolvedValue(
      makeResponse([
        {
          id: 'feat_1',
          name: 'Billing',
          content: 'Users can pay for tiered service plans.',
          display_order: 0,
        },
        {
          id: 'feat_2',
          name: 'Auth',
          content: 'Users sign in with email and password.',
          display_order: 1,
        },
        {
          id: 'feat_3',
          name: 'Reports',
          content: 'Users see usage stats on a dashboard.',
          display_order: 2,
        },
      ])
    );
    renderList(false);

    await waitFor(() => expect(screen.getByText('Billing')).toBeInTheDocument());
    expect(screen.getByText('Auth')).toBeInTheDocument();
    expect(screen.getByText('Reports')).toBeInTheDocument();
    expect(
      screen.getByText(/Users can pay for tiered service plans/)
    ).toBeInTheDocument();
    expect(screen.getByText(/Users sign in with email/)).toBeInTheDocument();
    expect(screen.getByText(/Users see usage stats/)).toBeInTheDocument();
    // Header shows count
    expect(screen.getByText(/Features \(3\)/)).toBeInTheDocument();
  });

  it('shows display_order badge on each feature', async () => {
    mockedGet.mockResolvedValue(
      makeResponse([
        { id: 'feat_1', name: 'First', content: 'a', display_order: 0 },
        { id: 'feat_2', name: 'Second', content: 'b', display_order: 1 },
      ])
    );
    renderList(false);
    await waitFor(() => expect(screen.getByText('First')).toBeInTheDocument());
    expect(screen.getByText('#0')).toBeInTheDocument();
    expect(screen.getByText('#1')).toBeInTheDocument();
  });

  it('shows error state when the query fails', async () => {
    mockedGet.mockRejectedValue({
      response: {
        status: 500,
        data: { detail: 'database offline' },
      },
    });
    renderList(false);
    await waitFor(() =>
      expect(screen.getByText(/database offline/i)).toBeInTheDocument()
    );
  });
});
