import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { StructureEdge, StructureNode, StructureResponse } from '../api/structure';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ComponentOverviewPanel } from './ComponentOverviewPanel';

vi.mock('../hooks/queries/useProjectStructure', () => ({
  useProjectStructure: vi.fn(() => ({ data: undefined })),
}));

import { useProjectStructure } from '../hooks/queries/useProjectStructure';

const mockedUseStructure = useProjectStructure as unknown as ReturnType<typeof vi.fn>;

function comp(overrides: Partial<StructureNode> = {}): StructureNode {
  return {
    id: 'comp_1',
    tier: 'comp',
    kind: 'domain',
    parent_id: null,
    name: 'Billing',
    display_order: 0,
    content: '',
    has_content: false,
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

function structure(
  nodes: StructureNode[],
  edges: StructureEdge[] = [],
): StructureResponse {
  return { offset: 0, nodes, edges };
}

function setStructure(s: StructureResponse | undefined) {
  mockedUseStructure.mockReturnValue({ data: s });
}

function renderPanel(
  props: { component: StructureNode; projectId?: string } = {
    component: comp(),
  },
) {
  return render(
    <TestQueryWrapper>
      <ComponentOverviewPanel
        projectId={props.projectId ?? 'proj_1'}
        component={props.component}
      />
    </TestQueryWrapper>,
  );
}

describe('ComponentOverviewPanel', () => {
  it('renders the component name + placeholders when fragments are empty', () => {
    setStructure(structure([comp()]));
    renderPanel();
    expect(screen.getByRole('heading', { name: 'Billing' })).toBeInTheDocument();
    const placeholders = screen.getAllByText(/Not yet populated/i);
    expect(placeholders.length).toBe(2);
  });

  it('renders techspec + pubapi bodies when populated, splitting paragraphs', () => {
    const c = comp({
      techspec: 'Runs as a Python service.\n\nUses PostgreSQL for persistence.',
      pubapi: 'Mints and refreshes session tokens.',
    });
    setStructure(structure([c]));
    renderPanel({ component: c });
    expect(screen.getByText('Runs as a Python service.')).toBeInTheDocument();
    expect(screen.getByText('Uses PostgreSQL for persistence.')).toBeInTheDocument();
    expect(screen.getByText('Mints and refreshes session tokens.')).toBeInTheDocument();
  });

  it('renders outbound and inbound dependency chips', () => {
    const me = comp({ id: 'comp_self', name: 'Self' });
    const dep = comp({ id: 'comp_dep', name: 'Auth' });
    const consumer = comp({ id: 'comp_consumer', name: 'Reports' });
    setStructure(
      structure(
        [me, dep, consumer],
        [
          { id: 'e1', edge_type: 'dependency', source_id: 'comp_self', target_id: 'comp_dep' },
          {
            id: 'e2',
            edge_type: 'dependency',
            source_id: 'comp_consumer',
            target_id: 'comp_self',
          },
        ],
      ),
    );
    renderPanel({ component: me });
    const outbound = screen.getByTestId('overview-outbound-deps');
    expect(outbound).toHaveTextContent('Auth');
    expect(outbound).toHaveTextContent('comp_dep');
    const inbound = screen.getByTestId('overview-inbound-deps');
    expect(inbound).toHaveTextContent('Reports');
    expect(inbound).toHaveTextContent('comp_consumer');
  });

  it('shows "Presents" only on presentational comps', () => {
    const ui = comp({ id: 'comp_ui', name: 'UI', kind: 'presentational' });
    const domain = comp({ id: 'comp_domain', name: 'Domain' });
    setStructure(
      structure(
        [ui, domain],
        [
          {
            id: 'e1',
            edge_type: 'domain_parent',
            source_id: 'comp_ui',
            target_id: 'comp_domain',
          },
        ],
      ),
    );
    renderPanel({ component: ui });
    expect(screen.getByTestId('overview-domain-parents')).toHaveTextContent('Domain');
  });

  it('shows "Presented by" on a domain comp with inbound domain_parent edges', () => {
    const domain = comp({ id: 'comp_domain', name: 'Domain' });
    const ui = comp({ id: 'comp_ui', name: 'UI', kind: 'presentational' });
    setStructure(
      structure(
        [domain, ui],
        [
          {
            id: 'e1',
            edge_type: 'domain_parent',
            source_id: 'comp_ui',
            target_id: 'comp_domain',
          },
        ],
      ),
    );
    renderPanel({ component: domain });
    expect(screen.getByTestId('overview-presenting-children')).toHaveTextContent('UI');
    // A domain comp shouldn't show the "Presents" section.
    expect(screen.queryByTestId('overview-domain-parents')).not.toBeInTheDocument();
  });

  it('reports empty-state hints when there are no relations', () => {
    setStructure(structure([comp()]));
    renderPanel();
    expect(screen.getByTestId('overview-outbound-deps')).toHaveTextContent(
      /No outbound dependencies/,
    );
    expect(screen.getByTestId('overview-inbound-deps')).toHaveTextContent(
      /Nothing depends on this component/,
    );
  });
});
