import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ElementDefinition, StylesheetCSS } from 'cytoscape';

// Mock DagCanvas so we can capture its props (notably
// ``onNodeDoubleTap`` and ``hiddenNodeTypes``) and invoke them
// imperatively without spinning up a real cytoscape instance.
// Layout-direction behavior lives in ``DagCanvas.test.tsx`` so
// this mock can stay pure.
let lastDoubleTap: ((nodeId: string) => void) | undefined;
let lastElements: ElementDefinition[] | undefined;
let lastHiddenTypes: ReadonlySet<string> | undefined;
vi.mock('./DagCanvas', () => ({
  DagCanvas: (props: {
    elements: ElementDefinition[];
    stylesheet: StylesheetCSS[];
    onNodeDoubleTap?: (nodeId: string) => void;
    hiddenNodeTypes?: ReadonlySet<string>;
  }) => {
    lastElements = props.elements;
    lastDoubleTap = props.onNodeDoubleTap;
    lastHiddenTypes = props.hiddenNodeTypes;
    return <div data-testid="cy-canvas" />;
  },
}));

const mockedStructure = vi.fn();
vi.mock('../../hooks/queries/useStructureForViz', () => ({
  useStructureForViz: () => mockedStructure(),
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

function makeStructure() {
  return {
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
  };
}

beforeEach(() => {
  mockedStructure.mockReset();
  lastDoubleTap = undefined;
  lastElements = undefined;
  lastHiddenTypes = undefined;
});

describe('FullDagView', () => {
  it('shows the loading state while structure is still in flight', () => {
    mockedStructure.mockReturnValue({ data: undefined, isLoading: true });
    renderAt('/p');
    expect(screen.getByText(/Loading graph/)).toBeInTheDocument();
  });

  it('renders the top-level hint pointing users at the decomposition tab', () => {
    mockedStructure.mockReturnValue({ data: makeStructure(), isLoading: false });
    renderAt('/p');
    expect(
      screen.getByText(/double-click a component to open its decomposition tab/i),
    ).toBeInTheDocument();
    expect(screen.getByTestId('cy-canvas')).toBeInTheDocument();
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

  it('double-tapping a top-level comp navigates to its decomposition tab', () => {
    mockedStructure.mockReturnValue({ data: makeStructure(), isLoading: false });
    renderAt('/p');
    expect(lastDoubleTap).toBeDefined();
    expect(lastElements?.some((el) => el.data?.id === 'comp_TOP00001')).toBe(
      true,
    );
    act(() => lastDoubleTap?.('comp_TOP00001'));
    expect(screen.getByTestId('loc').textContent).toBe(
      '/p?node=comp_TOP00001&view=decomposition',
    );
  });

  it('double-tapping a non-top-level node is a no-op', () => {
    mockedStructure.mockReturnValue({ data: makeStructure(), isLoading: false });
    renderAt('/p?something=else');
    act(() => lastDoubleTap?.('feat_xxx'));
    // URL stays on the original entry.
    expect(screen.getByTestId('loc').textContent).toBe('/p?something=else');
  });

  it('passes hiddenNodeTypes derived from ?hide= to DagCanvas', () => {
    mockedStructure.mockReturnValue({ data: makeStructure(), isLoading: false });
    renderAt('/p?hide=components');
    expect(lastHiddenTypes?.has('comp-top')).toBe(true);
  });

  it('renders the tier filter chip row when groups are available', () => {
    mockedStructure.mockReturnValue({ data: makeStructure(), isLoading: false });
    renderAt('/p');
    expect(screen.getByTestId('tier-filter-chips')).toBeInTheDocument();
    expect(screen.getByTestId('tier-filter-chip-components')).toBeInTheDocument();
  });

  it('toggling a chip writes ?hide= to the URL', () => {
    mockedStructure.mockReturnValue({ data: makeStructure(), isLoading: false });
    renderAt('/p');
    fireEvent.click(screen.getByTestId('tier-filter-chip-components'));
    expect(screen.getByTestId('loc').textContent).toBe('/p?hide=components');
  });

  it('toggling a hidden chip back removes ?hide= from the URL', () => {
    mockedStructure.mockReturnValue({ data: makeStructure(), isLoading: false });
    renderAt('/p?hide=components');
    fireEvent.click(screen.getByTestId('tier-filter-chip-components'));
    expect(screen.getByTestId('loc').textContent).toBe('/p');
  });
});
