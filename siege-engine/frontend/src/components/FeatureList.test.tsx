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
    group_label?: string | null;
    is_implicit?: boolean;
  }> = []
): FeatureListResponse {
  return {
    features: features.map((f) => ({
      id: f.id,
      name: f.name,
      content: f.content,
      display_order: f.display_order,
      group_label: f.group_label ?? null,
      is_implicit: f.is_implicit ?? false,
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

  it('renders features under their group headers', async () => {
    mockedGet.mockResolvedValue(
      makeResponse([
        {
          id: 'feat_1',
          name: 'Login',
          content: 'Users sign in.',
          display_order: 0,
          group_label: 'User Management',
        },
        {
          id: 'feat_2',
          name: 'Password Reset',
          content: 'Users reset via email.',
          display_order: 1,
          group_label: 'User Management',
          is_implicit: true,
        },
        {
          id: 'feat_3',
          name: 'Posting',
          content: 'Users create posts.',
          display_order: 2,
          group_label: 'Content',
        },
      ])
    );
    renderList(false);
    await waitFor(() => expect(screen.getByText('Login')).toBeInTheDocument());
    // Group headers (use getAllByText since count annotation adds
    // sibling text inside the same header)
    expect(screen.getByText('User Management')).toBeInTheDocument();
    expect(screen.getByText('Content')).toBeInTheDocument();
    // All three features render
    expect(screen.getByText('Login')).toBeInTheDocument();
    expect(screen.getByText('Password Reset')).toBeInTheDocument();
    expect(screen.getByText('Posting')).toBeInTheDocument();
  });

  it('renders an implicit badge on inferred features', async () => {
    mockedGet.mockResolvedValue(
      makeResponse([
        {
          id: 'feat_1',
          name: 'Login',
          content: 'Users sign in.',
          display_order: 0,
          is_implicit: false,
        },
        {
          id: 'feat_2',
          name: 'Password Reset',
          content: 'Users reset via email.',
          display_order: 1,
          is_implicit: true,
        },
      ])
    );
    renderList(false);
    await waitFor(() =>
      expect(screen.getByText('Password Reset')).toBeInTheDocument()
    );
    // The "inferred" badge renders for the implicit feature only.
    const inferredBadges = screen.getAllByText(/inferred/i);
    expect(inferredBadges).toHaveLength(1);
  });

  it('renders mixed grouped + ungrouped features with an Ungrouped section', async () => {
    mockedGet.mockResolvedValue(
      makeResponse([
        {
          id: 'feat_1',
          name: 'Login',
          content: 'Users sign in.',
          display_order: 0,
          group_label: 'User Management',
        },
        {
          id: 'feat_2',
          name: 'Global Search',
          content: 'Search everything.',
          display_order: 1,
          group_label: null,
        },
      ])
    );
    renderList(false);
    await waitFor(() => expect(screen.getByText('Login')).toBeInTheDocument());
    expect(screen.getByText('User Management')).toBeInTheDocument();
    expect(screen.getByText('Ungrouped')).toBeInTheDocument();
    expect(screen.getByText('Global Search')).toBeInTheDocument();
  });
});
