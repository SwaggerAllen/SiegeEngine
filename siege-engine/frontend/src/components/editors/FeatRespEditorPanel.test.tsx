import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { StructureResponse } from '../../api/structure';
import { TestQueryWrapper } from '../../test/queryWrapper';
import { FeatRespEditorPanel } from './FeatRespEditorPanel';

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
  tier: 'feat' | 'resp',
  opts: { is_deferred?: boolean } = {},
) {
  return {
    id,
    name,
    tier,
    kind: 'domain',
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
    is_deferred: opts.is_deferred ?? false,
  };
}

function structure(): StructureResponse {
  return {
    offset: 1,
    nodes: [
      node('feat_A', 'Billing', 'feat'),
      node('feat_B', 'Auth', 'feat'),
      node('resp_1', 'persist_invoice', 'resp'),
      node('resp_2', 'authenticate_user', 'resp'),
    ],
    edges: [
      {
        id: 'edge_1',
        edge_type: 'decomposition',
        source_id: 'feat_A',
        target_id: 'resp_1',
      },
    ],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FeatRespEditorPanel', () => {
  it('lists existing feat→resp decomposition edges', async () => {
    mockedStructure.mockResolvedValue(structure());
    render(
      <TestQueryWrapper>
        <FeatRespEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Billing → persist_invoice/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/Coverage \(1\)/)).toBeInTheDocument();
  });

  it('enqueues AddDecomposition when Queue add is clicked', async () => {
    mockedStructure.mockResolvedValue(structure());
    mockedEnqueue.mockResolvedValue({ sequence: 2 });
    render(
      <TestQueryWrapper>
        <FeatRespEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Queue add/ })).toBeInTheDocument(),
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/Feature/) as HTMLSelectElement,
      'feat_B',
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/Responsibility/) as HTMLSelectElement,
      'resp_2',
    );
    await userEvent.click(screen.getByRole('button', { name: /Queue add/ }));
    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'AddDecomposition',
      source_id: 'feat_B',
      source_name: 'Auth',
      target_id: 'resp_2',
      target_name: 'authenticate_user',
    });
  });

  it('enqueues RemoveDecomposition on Queue remove', async () => {
    mockedStructure.mockResolvedValue(structure());
    mockedEnqueue.mockResolvedValue({ sequence: 2 });
    render(
      <TestQueryWrapper>
        <FeatRespEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Billing → persist_invoice/)).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole('button', { name: /Queue remove/ }));
    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'RemoveDecomposition',
      source_id: 'feat_A',
      source_name: 'Billing',
      target_id: 'resp_1',
      target_name: 'persist_invoice',
    });
  });

  it('enqueues a Promote instruction (feat → resp) on Queue promote', async () => {
    mockedStructure.mockResolvedValue(structure());
    mockedEnqueue.mockResolvedValue({ sequence: 5 });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(
      <TestQueryWrapper>
        <FeatRespEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Feature deferral/i)).toBeInTheDocument(),
    );
    const promoteButtons = screen.getAllByRole('button', { name: /Queue promote/ });
    await userEvent.click(promoteButtons[0]);
    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'Promote',
      node_id: 'feat_A',
      name: 'Billing',
      new_tier: 'resp',
    });
  });

  it('Promote skips when the confirm dialog is cancelled', async () => {
    mockedStructure.mockResolvedValue(structure());
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(
      <TestQueryWrapper>
        <FeatRespEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Feature deferral/i)).toBeInTheDocument(),
    );
    const promoteButtons = screen.getAllByRole('button', { name: /Queue promote/ });
    await userEvent.click(promoteButtons[0]);
    expect(mockedEnqueue).not.toHaveBeenCalled();
  });

  it('enqueues SetFeatureDeferred when the Defer button is clicked', async () => {
    mockedStructure.mockResolvedValue(structure());
    mockedEnqueue.mockResolvedValue({ sequence: 3 });
    render(
      <TestQueryWrapper>
        <FeatRespEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Feature deferral/i)).toBeInTheDocument(),
    );
    // feat_A is "Billing" (not deferred). Clicking "Queue defer" flips it.
    const deferButtons = screen.getAllByRole('button', { name: /Queue defer/ });
    await userEvent.click(deferButtons[0]);
    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'SetFeatureDeferred',
      node_id: 'feat_A',
      name: 'Billing',
      is_deferred: true,
    });
  });

  it('renders a deferred feature dimmed with an un-defer affordance', async () => {
    mockedStructure.mockResolvedValue({
      offset: 1,
      nodes: [
        node('feat_A', 'Billing', 'feat', { is_deferred: true }),
        node('resp_1', 'persist_invoice', 'resp'),
      ],
      edges: [],
    });
    mockedEnqueue.mockResolvedValue({ sequence: 4 });
    render(
      <TestQueryWrapper>
        <FeatRespEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Billing \(deferred\)/)).toBeInTheDocument(),
    );
    const undeferBtn = screen.getByRole('button', { name: /Queue un-defer/ });
    await userEvent.click(undeferBtn);
    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'SetFeatureDeferred',
      node_id: 'feat_A',
      name: 'Billing',
      is_deferred: false,
    });
  });
});
