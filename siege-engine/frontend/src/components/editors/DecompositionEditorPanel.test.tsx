import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { StructureResponse } from '../../api/structure';
import { TestQueryWrapper } from '../../test/queryWrapper';
import { DecompositionEditorPanel } from './DecompositionEditorPanel';

vi.mock('../../api/structure', async () => {
  const actual =
    await vi.importActual<typeof import('../../api/structure')>('../../api/structure');
  return { ...actual, getProjectStructure: vi.fn() };
});

vi.mock('../../api/queue', async () => {
  const actual = await vi.importActual<typeof import('../../api/queue')>('../../api/queue');
  return {
    ...actual,
    enqueueInstruction: vi.fn(),
    // Deterministic minter so tests can match the generated id.
    mintClientId: vi.fn((kind: string) => `${kind}_TEST0001`),
  };
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
  parent_id: string | null = null,
  kind: 'domain' | 'presentational' = 'domain',
) {
  return {
    id,
    name,
    tier: 'comp',
    kind,
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
      node('comp_TOP', 'Billing'),
      node('comp_SUB', 'BillingStore', 'comp_TOP'),
    ],
    edges: [],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DecompositionEditorPanel', () => {
  it('renders the top-level comp tree with its subcomps', async () => {
    mockedStructure.mockResolvedValue(structure());
    render(
      <TestQueryWrapper>
        <DecompositionEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() => expect(screen.getByText('Billing')).toBeInTheDocument());
    expect(screen.getByText('BillingStore')).toBeInTheDocument();
  });

  it('enqueues a top-level Create instruction', async () => {
    mockedStructure.mockResolvedValue({ offset: 1, nodes: [], edges: [] });
    mockedEnqueue.mockResolvedValue({ sequence: 1 });
    render(
      <TestQueryWrapper>
        <DecompositionEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Queue create/ })).toBeInTheDocument(),
    );
    await userEvent.type(
      screen.getByPlaceholderText('Component name'),
      'NewComp',
    );
    await userEvent.click(screen.getByRole('button', { name: /Queue create/ }));
    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'Create',
      node_id: 'comp_TEST0001',
      tier: 'comp',
      name: 'NewComp',
      parent_id: null,
      parent_name: null,
    });
  });

  it('enqueues a Rename instruction via the prompt dialog', async () => {
    mockedStructure.mockResolvedValue(structure());
    mockedEnqueue.mockResolvedValue({ sequence: 1 });
    vi.spyOn(window, 'prompt').mockReturnValue('Payments');
    render(
      <TestQueryWrapper>
        <DecompositionEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() => expect(screen.getByText('Billing')).toBeInTheDocument());
    // First Rename button is for the top-level 'Billing' comp.
    await userEvent.click(screen.getAllByRole('button', { name: /^Rename$/ })[0]);
    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'Rename',
      node_id: 'comp_TOP',
      old_name: 'Billing',
      new_name: 'Payments',
    });
  });

  it('enqueues a Delete instruction after confirmation', async () => {
    mockedStructure.mockResolvedValue(structure());
    mockedEnqueue.mockResolvedValue({ sequence: 1 });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(
      <TestQueryWrapper>
        <DecompositionEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() => expect(screen.getByText('Billing')).toBeInTheDocument());
    await userEvent.click(screen.getAllByRole('button', { name: /^Delete$/ })[0]);
    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'Delete',
      node_id: 'comp_TOP',
      name: 'Billing',
    });
  });

  it('skips Delete when the user cancels the confirm dialog', async () => {
    mockedStructure.mockResolvedValue(structure());
    mockedEnqueue.mockResolvedValue({ sequence: 1 });
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(
      <TestQueryWrapper>
        <DecompositionEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() => expect(screen.getByText('Billing')).toBeInTheDocument());
    await userEvent.click(screen.getAllByRole('button', { name: /^Delete$/ })[0]);
    expect(mockedEnqueue).not.toHaveBeenCalled();
  });

  it('enqueues a child Create instruction with the parent id + name', async () => {
    mockedStructure.mockResolvedValue(structure());
    mockedEnqueue.mockResolvedValue({ sequence: 1 });
    render(
      <TestQueryWrapper>
        <DecompositionEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() => expect(screen.getByText('Billing')).toBeInTheDocument());
    // Click "Add child" on the top-level Billing comp.
    await userEvent.click(screen.getByRole('button', { name: /Add child/ }));
    await userEvent.type(
      screen.getByPlaceholderText('Subcomponent name'),
      'Receipts',
    );
    // There are two "Queue create" buttons — top-level and inline
    // child form. Pick the inline one via its surrounding form.
    const buttons = screen.getAllByRole('button', { name: /Queue create/ });
    // The inline button appears second (top-level form is first).
    await userEvent.click(buttons[buttons.length - 1]);
    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'Create',
      node_id: 'comp_TEST0001',
      tier: 'comp',
      name: 'Receipts',
      parent_id: 'comp_TOP',
      parent_name: 'Billing',
    });
  });
});
