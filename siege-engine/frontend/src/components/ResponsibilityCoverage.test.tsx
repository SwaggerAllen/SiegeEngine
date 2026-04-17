import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ResponsibilityCoverage as Coverage } from '../api/responsibilityCoverage';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ResponsibilityCoverage } from './ResponsibilityCoverage';

vi.mock('../api/responsibilityCoverage', async () => {
  const actual = await vi.importActual<
    typeof import('../api/responsibilityCoverage')
  >('../api/responsibilityCoverage');
  return {
    ...actual,
    getResponsibilityCoverage: vi.fn(),
  };
});

import * as api from '../api/responsibilityCoverage';

const mocked = api.getResponsibilityCoverage as unknown as ReturnType<typeof vi.fn>;

function fixture(overrides: Partial<Coverage> = {}): Coverage {
  return {
    received: [],
    computed: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ResponsibilityCoverage', () => {
  it('renders both groups with counts and items', async () => {
    mocked.mockResolvedValue(
      fixture({
        received: [
          {
            id: 'resp_RRRR1111',
            name: 'Authenticate users',
            content: 'Verify creds.',
            display_order: 0,
            updated_at: '2026-04-17T00:00:00',
          },
          {
            id: 'resp_RRRR2222',
            name: 'Manage sessions',
            content: 'Maintain sessions.',
            display_order: 1,
            updated_at: '2026-04-17T00:00:00',
          },
        ],
        computed: [
          {
            id: 'resp_SSSS1111',
            name: 'Password hashing',
            content: 'Bcrypt with work factor.',
            display_order: 0,
            updated_at: '2026-04-17T00:00:00',
          },
        ],
      }),
    );

    render(
      <TestQueryWrapper>
        <ResponsibilityCoverage projectId="p1" compId="c1" />
      </TestQueryWrapper>,
    );

    await waitFor(() =>
      expect(screen.getByText('Authenticate users')).toBeInTheDocument(),
    );
    expect(screen.getByText('Received')).toBeInTheDocument();
    expect(screen.getByText('Computed')).toBeInTheDocument();
    expect(screen.getByText('Manage sessions')).toBeInTheDocument();
    expect(screen.getByText('Password hashing')).toBeInTheDocument();
    expect(screen.getByText('Verify creds.')).toBeInTheDocument();
    expect(screen.getByText('Bcrypt with work factor.')).toBeInTheDocument();
    // Each resp shows its id
    expect(screen.getByText('resp_RRRR1111')).toBeInTheDocument();
    expect(screen.getByText('resp_SSSS1111')).toBeInTheDocument();
  });

  it('shows empty hints for each group when the list is empty', async () => {
    mocked.mockResolvedValue(fixture());

    render(
      <TestQueryWrapper>
        <ResponsibilityCoverage projectId="p1" compId="c1" />
      </TestQueryWrapper>,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/No top-level responsibilities assigned/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/No subresponsibilities yet/)).toBeInTheDocument();
  });

  it('renders received without computed', async () => {
    mocked.mockResolvedValue(
      fixture({
        received: [
          {
            id: 'resp_A',
            name: 'A',
            content: '',
            display_order: 0,
            updated_at: '2026-04-17T00:00:00',
          },
        ],
      }),
    );

    render(
      <TestQueryWrapper>
        <ResponsibilityCoverage projectId="p1" compId="c1" />
      </TestQueryWrapper>,
    );

    await waitFor(() => expect(screen.getByText('A')).toBeInTheDocument());
    expect(screen.getByText(/No subresponsibilities yet/)).toBeInTheDocument();
  });
});
