import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ElementDefinition, StylesheetCSS } from 'cytoscape';
import type { StructureNode } from '../../api/structure';

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
vi.mock('../../hooks/queries/useProjectStructure', () => ({
  useProjectStructure: () => mockedStructure(),
}));

import { ComponentDecompositionPanel } from './ComponentDecompositionPanel';

function n(
  id: string,
  tier: string,
  parent_id: string | null,
  overrides: Partial<StructureNode> = {},
): StructureNode {
  return {
    id,
    tier,
    kind: 'domain',
    parent_id,
    name: id,
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
    ...overrides,
  };
}

function LocationReporter() {
  const location = useLocation();
  return <div data-testid="loc">{`${location.pathname}${location.search}`}</div>;
}

function renderAt(initialEntry: string, componentId: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route
            path="/p"
            element={
              <ComponentDecompositionPanel
                projectId="proj_1"
                componentId={componentId}
              />
            }
          />
        </Routes>
        <LocationReporter />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedStructure.mockReset();
  lastDoubleTap = undefined;
  lastElements = undefined;
  lastHiddenTypes = undefined;
});

describe('ComponentDecompositionPanel', () => {
  it('shows a loading state while structure is in flight', () => {
    mockedStructure.mockReturnValue({ data: undefined, isLoading: true });
    renderAt('/p', 'comp_1');
    expect(screen.getByText(/Loading graph/)).toBeInTheDocument();
  });

  it('renders an empty-state message for a comp with no subcomponents', () => {
    mockedStructure.mockReturnValue({
      data: {
        offset: 1,
        // A top-level comp with no children — drillElements returns
        // only the comp itself, but with no children we should show
        // the "not fanned out" message rather than an empty canvas.
        // We simulate that by making drillElements yield zero
        // elements via an empty node list.
        nodes: [],
        edges: [],
      },
      isLoading: false,
    });
    renderAt('/p', 'comp_1');
    expect(
      screen.getByText(/this component hasn't fanned out/i),
    ).toBeInTheDocument();
  });

  it('renders the canvas with subcomp + impl elements when present', () => {
    mockedStructure.mockReturnValue({
      data: {
        offset: 1,
        nodes: [
          n('comp_1', 'comp', null, { name: 'Billing' }),
          n('comp_sub1', 'comp', 'comp_1', { name: 'TokenStore' }),
          n('impl_sub1', 'impl', 'comp_sub1'),
        ],
        edges: [],
      },
      isLoading: false,
    });
    renderAt('/p', 'comp_1');
    expect(screen.getByTestId('cy-canvas')).toBeInTheDocument();
    const ids = (lastElements ?? []).map((el) => el.data?.id);
    expect(ids).toContain('comp_sub1');
    // Impls render unconditionally — no reveal-on-click in this view.
    expect(ids).toContain('impl_sub1');
  });

  it('double-tapping a subcomponent navigates to its node page', () => {
    mockedStructure.mockReturnValue({
      data: {
        offset: 1,
        nodes: [
          n('comp_1', 'comp', null, { name: 'Billing' }),
          n('comp_sub1', 'comp', 'comp_1', { name: 'TokenStore' }),
        ],
        edges: [],
      },
      isLoading: false,
    });
    renderAt('/p?view=decomposition', 'comp_1');
    expect(lastDoubleTap).toBeDefined();
    act(() => lastDoubleTap?.('comp_sub1'));
    // The view param is cleared so the subcomp lands on its own
    // default tab (Subcomparch) rather than inheriting the comp's
    // ``view=decomposition``.
    expect(screen.getByTestId('loc').textContent).toBe('/p?node=comp_sub1');
  });

  it('double-tapping the drilled comp itself is a no-op', () => {
    mockedStructure.mockReturnValue({
      data: {
        offset: 1,
        nodes: [
          n('comp_1', 'comp', null, { name: 'Billing' }),
          n('comp_sub1', 'comp', 'comp_1', { name: 'TokenStore' }),
        ],
        edges: [],
      },
      isLoading: false,
    });
    renderAt('/p?view=decomposition', 'comp_1');
    act(() => lastDoubleTap?.('comp_1'));
    expect(screen.getByTestId('loc').textContent).toBe(
      '/p?view=decomposition',
    );
  });

  it('?hide= is preserved across selection but cleared on subcomp navigation', () => {
    mockedStructure.mockReturnValue({
      data: {
        offset: 1,
        nodes: [
          n('comp_1', 'comp', null, { name: 'Billing' }),
          n('comp_sub1', 'comp', 'comp_1', { name: 'TokenStore' }),
        ],
        edges: [],
      },
      isLoading: false,
    });
    renderAt('/p?view=decomposition&hide=implementations', 'comp_1');
    expect(lastHiddenTypes?.has('impl')).toBe(true);
    // Navigating to a subcomp clears ``hide`` so the subcomp lands
    // on a fresh, unfiltered view of its own decomposition.
    act(() => lastDoubleTap?.('comp_sub1'));
    expect(screen.getByTestId('loc').textContent).toBe('/p?node=comp_sub1');
  });

  it('renders the tier filter chip row when groups are available', () => {
    mockedStructure.mockReturnValue({
      data: {
        offset: 1,
        nodes: [
          n('comp_1', 'comp', null, { name: 'Billing' }),
          n('comp_sub1', 'comp', 'comp_1', { name: 'TokenStore' }),
        ],
        edges: [],
      },
      isLoading: false,
    });
    renderAt('/p?view=decomposition', 'comp_1');
    expect(screen.getByTestId('tier-filter-chips')).toBeInTheDocument();
    expect(screen.getByTestId('tier-filter-chip-subcomponents')).toBeInTheDocument();
  });

  it('toggling a chip writes ?hide= alongside ?view=decomposition', () => {
    mockedStructure.mockReturnValue({
      data: {
        offset: 1,
        nodes: [
          n('comp_1', 'comp', null, { name: 'Billing' }),
          n('comp_sub1', 'comp', 'comp_1', { name: 'TokenStore' }),
        ],
        edges: [],
      },
      isLoading: false,
    });
    renderAt('/p?view=decomposition', 'comp_1');
    fireEvent.click(screen.getByTestId('tier-filter-chip-subcomponents'));
    expect(screen.getByTestId('loc').textContent).toBe(
      '/p?view=decomposition&hide=subcomponents',
    );
  });
});
