import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { StructureResponse } from '../../api/structure';
import { TestQueryWrapper } from '../../test/queryWrapper';
import { DomainParentEditorPanel } from './DomainParentEditorPanel';

vi.mock('../../api/structure', async () => {
  const actual =
    await vi.importActual<typeof import('../../api/structure')>('../../api/structure');
  return { ...actual, getProjectStructure: vi.fn() };
});

vi.mock('../../api/queue', async () => {
  const actual = await vi.importActual<typeof import('../../api/queue')>('../../api/queue');
  return { ...actual, enqueueInstruction: vi.fn() };
});

import * as structureApi from '../../api/structure';
import * as queueApi from '../../api/queue';

const mockedStructure = structureApi.getProjectStructure as unknown as ReturnType<
  typeof vi.fn
>;
const mockedEnqueue = queueApi.enqueueInstruction as unknown as ReturnType<typeof vi.fn>;

function node(
  id: string,
  name: string,
  kind: 'domain' | 'presentational' = 'domain',
) {
  return {
    id,
    name,
    tier: 'comp',
    kind,
    parent_id: null,
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
  };
}

function makeStructure(): StructureResponse {
  return {
    offset: 1,
    nodes: [
      node('comp_BILL', 'Billing', 'domain'),
      node('comp_BILLUI', 'BillingUI', 'presentational'),
      node('comp_USERUI', 'UserUI', 'presentational'),
    ],
    edges: [
      {
        id: 'edge_1',
        edge_type: 'domain_parent',
        source_id: 'comp_BILLUI',
        target_id: 'comp_BILL',
      },
    ],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DomainParentEditorPanel', () => {
  it('lists existing domain-parent edges by name', async () => {
    mockedStructure.mockResolvedValue(makeStructure());
    render(
      <TestQueryWrapper>
        <DomainParentEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/BillingUI presents Billing/)).toBeInTheDocument(),
    );
  });

  it('enqueues AddDomainParent with presentational source + domain target', async () => {
    mockedStructure.mockResolvedValue(makeStructure());
    mockedEnqueue.mockResolvedValue({ sequence: 2 });
    render(
      <TestQueryWrapper>
        <DomainParentEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Queue add/ })).toBeInTheDocument(),
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/Presentational/) as HTMLSelectElement,
      'comp_USERUI',
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/Domain/) as HTMLSelectElement,
      'comp_BILL',
    );
    await userEvent.click(screen.getByRole('button', { name: /Queue add/ }));

    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'AddDomainParent',
      source_id: 'comp_USERUI',
      source_name: 'UserUI',
      target_id: 'comp_BILL',
      target_name: 'Billing',
    });
  });

  it('enqueues RemoveDomainParent from an existing edge', async () => {
    mockedStructure.mockResolvedValue(makeStructure());
    mockedEnqueue.mockResolvedValue({ sequence: 2 });
    render(
      <TestQueryWrapper>
        <DomainParentEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/BillingUI presents Billing/)).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole('button', { name: /Queue remove/ }));
    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'RemoveDomainParent',
      source_id: 'comp_BILLUI',
      source_name: 'BillingUI',
      target_id: 'comp_BILL',
      target_name: 'Billing',
    });
  });

  it('shows warning when no presentational comps exist', async () => {
    mockedStructure.mockResolvedValue({
      offset: 1,
      nodes: [node('comp_A', 'A', 'domain')],
      edges: [],
    });
    render(
      <TestQueryWrapper>
        <DomainParentEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(
        screen.getByText(/No presentational components exist yet/),
      ).toBeInTheDocument(),
    );
  });
});
