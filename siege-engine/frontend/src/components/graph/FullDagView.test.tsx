import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Mock react-cytoscapejs so the test doesn't spin up a real
// cytoscape instance (jsdom has no canvas). We only care about
// the header / drill-state behavior here; the element composition
// is covered by elements.test.ts and reachable.test.ts.
vi.mock('react-cytoscapejs', () => ({
  default: () => <div data-testid="cy-canvas" />,
}));

// Mock the structure query to avoid the network.
const mockedStructure = vi.fn();
vi.mock('../../hooks/queries/useProjectStructure', () => ({
  useProjectStructure: () => mockedStructure(),
}));

import { FullDagView } from './FullDagView';

function LocationReporter() {
  const location = useLocation();
  return <div data-testid="loc">{`${location.pathname}${location.search}`}</div>;
}

function renderAt(initialEntry: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/p" element={<FullDagView projectId="proj_1" />} />
        </Routes>
        <LocationReporter />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedStructure.mockReset();
});

describe('FullDagView', () => {
  it('shows the loading state while structure is still in flight', () => {
    mockedStructure.mockReturnValue({ data: undefined, isLoading: true });
    renderAt('/p');
    expect(screen.getByText(/Loading graph/)).toBeInTheDocument();
  });

  it('renders the top-level hint when no drill is set', () => {
    mockedStructure.mockReturnValue({
      data: {
        offset: 1,
        nodes: [
          {
            id: 'comp_TOP00001',
            tier: 'comp',
            kind: 'domain',
            parent_id: null,
            name: 'Billing',
            display_order: 0,
            content: '',
            has_content: true,
            has_pending_draft: false,
            generation_running: false,
            has_error: false,
            needs_user_action: false,
            is_stale: false,
            staleness_reasons: [],
            techspec: '',
            pubapi: '',
    is_deferred: false,
          },
        ],
        edges: [],
      },
      isLoading: false,
    });
    renderAt('/p');
    expect(
      screen.getByText(/double-click a component to drill in/i),
    ).toBeInTheDocument();
    expect(screen.getByTestId('cy-canvas')).toBeInTheDocument();
  });

  it('shows the drill header + Back button when ?drill is set', async () => {
    mockedStructure.mockReturnValue({
      data: {
        offset: 1,
        nodes: [
          {
            id: 'comp_TOP00001',
            tier: 'comp',
            kind: 'domain',
            parent_id: null,
            name: 'Billing',
            display_order: 0,
            content: '',
            has_content: true,
            has_pending_draft: false,
            generation_running: false,
            has_error: false,
            needs_user_action: false,
            is_stale: false,
            staleness_reasons: [],
            techspec: '',
            pubapi: '',
    is_deferred: false,
          },
        ],
        edges: [],
      },
      isLoading: false,
    });
    renderAt('/p?drill=comp_TOP00001');
    expect(screen.getByText(/Drilled into/i)).toBeInTheDocument();
    expect(screen.getByText('Billing')).toBeInTheDocument();

    const back = screen.getByRole('button', { name: /Back/i });
    await userEvent.click(back);
    expect(screen.getByTestId('loc').textContent).toBe('/p');
  });

  it('renders an error state when the structure fetch fails', () => {
    mockedStructure.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('boom'),
    });
    renderAt('/p');
    expect(
      screen.getByText(/Failed to load the decomposition graph/i),
    ).toBeInTheDocument();
  });
});
