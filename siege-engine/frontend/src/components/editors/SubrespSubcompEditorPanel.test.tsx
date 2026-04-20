import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { StructureResponse } from '../../api/structure';
import { TestQueryWrapper } from '../../test/queryWrapper';
import { SubrespSubcompEditorPanel } from './SubrespSubcompEditorPanel';

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
  tier: 'comp' | 'resp',
  parent_id: string | null,
) {
  return {
    id,
    name,
    tier,
    kind: 'domain',
    parent_id,
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
  };
}

function structure(): StructureResponse {
  return {
    offset: 1,
    nodes: [
      node('comp_TOP', 'Billing', 'comp', null),
      node('comp_SUB1', 'BillingStore', 'comp', 'comp_TOP'),
      node('comp_SUB2', 'BillingGateway', 'comp', 'comp_TOP'),
      node('resp_1', 'persist_invoice', 'resp', 'comp_SUB1'),
    ],
    edges: [],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SubrespSubcompEditorPanel', () => {
  it('lists subresponsibilities once a top-level comp is selected', async () => {
    mockedStructure.mockResolvedValue(structure());
    render(
      <TestQueryWrapper>
        <SubrespSubcompEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByLabelText(/Top-level component/)).toBeInTheDocument(),
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/Top-level component/) as HTMLSelectElement,
      'comp_TOP',
    );
    expect(screen.getByText('persist_invoice')).toBeInTheDocument();
    expect(screen.getByText(/Subresponsibilities \(1\)/)).toBeInTheDocument();
  });

  it('enqueues ReassignMapping when the parent dropdown changes', async () => {
    mockedStructure.mockResolvedValue(structure());
    mockedEnqueue.mockResolvedValue({ sequence: 1 });
    render(
      <TestQueryWrapper>
        <SubrespSubcompEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByLabelText(/Top-level component/)).toBeInTheDocument(),
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/Top-level component/) as HTMLSelectElement,
      'comp_TOP',
    );

    // Find the parent dropdown for the subresp row and pick a
    // different subcomp.
    const parentDropdowns = screen.getAllByLabelText(/Parent/);
    await userEvent.selectOptions(
      parentDropdowns[parentDropdowns.length - 1] as HTMLSelectElement,
      'comp_SUB2',
    );
    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'ReassignMapping',
      node_id: 'resp_1',
      name: 'persist_invoice',
      new_parent_id: 'comp_SUB2',
      new_parent_name: 'BillingGateway',
    });
  });

  it('warns when the selected top-level comp has no subcomponents yet', async () => {
    mockedStructure.mockResolvedValue({
      offset: 1,
      nodes: [node('comp_TOP', 'Solo', 'comp', null)],
      edges: [],
    });
    render(
      <TestQueryWrapper>
        <SubrespSubcompEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByLabelText(/Top-level component/)).toBeInTheDocument(),
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/Top-level component/) as HTMLSelectElement,
      'comp_TOP',
    );
    expect(screen.getByText(/has no subcomponents yet/)).toBeInTheDocument();
  });
});
