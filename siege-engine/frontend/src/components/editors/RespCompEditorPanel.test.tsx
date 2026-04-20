import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { StructureResponse } from '../../api/structure';
import { TestQueryWrapper } from '../../test/queryWrapper';
import { RespCompEditorPanel } from './RespCompEditorPanel';

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
  tier: 'resp' | 'comp',
  parent_id: string | null = null,
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
  };
}

function structure(): StructureResponse {
  return {
    offset: 1,
    nodes: [
      node('resp_1', 'persist_invoice', 'resp'),
      node('resp_2', 'authenticate', 'resp'),
      node('comp_BILL', 'Billing', 'comp'),
      node('comp_AUTH', 'Auth', 'comp'),
    ],
    edges: [
      {
        id: 'edge_1',
        edge_type: 'decomposition',
        source_id: 'resp_1',
        target_id: 'comp_BILL',
      },
    ],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('RespCompEditorPanel', () => {
  it('renders one dropdown per top-level resp with the current assignment', async () => {
    mockedStructure.mockResolvedValue(structure());
    render(
      <TestQueryWrapper>
        <RespCompEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText('persist_invoice')).toBeInTheDocument(),
    );
    // resp_1 is assigned to Billing; resp_2 unassigned.
    const dropdowns = screen.getAllByLabelText(/Assigned to/) as HTMLSelectElement[];
    expect(dropdowns[0].value).toBe('comp_BILL');
    expect(dropdowns[1].value).toBe('');
  });

  it('enqueues Remove + Add when reassigning an assigned resp', async () => {
    mockedStructure.mockResolvedValue(structure());
    mockedEnqueue.mockResolvedValue({ sequence: 1 });
    render(
      <TestQueryWrapper>
        <RespCompEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText('persist_invoice')).toBeInTheDocument(),
    );
    const dropdowns = screen.getAllByLabelText(/Assigned to/) as HTMLSelectElement[];
    await userEvent.selectOptions(dropdowns[0], 'comp_AUTH');
    // Two calls: Remove then Add.
    expect(mockedEnqueue).toHaveBeenNthCalledWith(1, 'p1', {
      instruction_type: 'RemoveDecomposition',
      source_id: 'resp_1',
      source_name: 'persist_invoice',
      target_id: 'comp_BILL',
      target_name: 'Billing',
    });
    expect(mockedEnqueue).toHaveBeenNthCalledWith(2, 'p1', {
      instruction_type: 'AddDecomposition',
      source_id: 'resp_1',
      source_name: 'persist_invoice',
      target_id: 'comp_AUTH',
      target_name: 'Auth',
    });
  });

  it('enqueues only an Add when the resp is currently unassigned', async () => {
    mockedStructure.mockResolvedValue(structure());
    mockedEnqueue.mockResolvedValue({ sequence: 1 });
    render(
      <TestQueryWrapper>
        <RespCompEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText('authenticate')).toBeInTheDocument(),
    );
    const dropdowns = screen.getAllByLabelText(/Assigned to/) as HTMLSelectElement[];
    await userEvent.selectOptions(dropdowns[1], 'comp_AUTH');
    expect(mockedEnqueue).toHaveBeenCalledTimes(1);
    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'AddDecomposition',
      source_id: 'resp_2',
      source_name: 'authenticate',
      target_id: 'comp_AUTH',
      target_name: 'Auth',
    });
  });
});
