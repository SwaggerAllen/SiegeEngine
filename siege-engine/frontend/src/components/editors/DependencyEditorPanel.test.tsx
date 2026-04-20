import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { StructureResponse } from '../../api/structure';
import { TestQueryWrapper } from '../../test/queryWrapper';
import { DependencyEditorPanel } from './DependencyEditorPanel';

vi.mock('../../api/structure', async () => {
  const actual =
    await vi.importActual<typeof import('../../api/structure')>('../../api/structure');
  return {
    ...actual,
    getProjectStructure: vi.fn(),
  };
});

vi.mock('../../api/queue', async () => {
  const actual = await vi.importActual<typeof import('../../api/queue')>('../../api/queue');
  return {
    ...actual,
    enqueueInstruction: vi.fn(),
  };
});

import * as structureApi from '../../api/structure';
import * as queueApi from '../../api/queue';

const mockedStructure = structureApi.getProjectStructure as unknown as ReturnType<
  typeof vi.fn
>;
const mockedEnqueue = queueApi.enqueueInstruction as unknown as ReturnType<typeof vi.fn>;

function makeStructure(): StructureResponse {
  return {
    offset: 1,
    nodes: [
      // Two top-level comps + one existing dependency edge A → B.
      node('comp_A', 'A'),
      node('comp_B', 'B'),
      node('comp_C', 'C'),
    ],
    edges: [
      {
        id: 'edge_AB',
        edge_type: 'dependency',
        source_id: 'comp_A',
        target_id: 'comp_B',
      },
    ],
  };
}

function node(id: string, name: string, parent_id: string | null = null) {
  return {
    id,
    name,
    tier: 'comp',
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

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DependencyEditorPanel', () => {
  it('lists existing dependency edges by name', async () => {
    mockedStructure.mockResolvedValue(makeStructure());
    render(
      <TestQueryWrapper>
        <DependencyEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/A → B/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/Existing dependencies \(1\)/)).toBeInTheDocument();
  });

  it('enqueues AddDependency with resolved names when Queue add is clicked', async () => {
    mockedStructure.mockResolvedValue(makeStructure());
    mockedEnqueue.mockResolvedValue({ sequence: 2 });
    render(
      <TestQueryWrapper>
        <DependencyEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Queue add/ })).toBeInTheDocument(),
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/From/) as HTMLSelectElement,
      'comp_A',
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/To/) as HTMLSelectElement,
      'comp_C',
    );
    await userEvent.click(screen.getByRole('button', { name: /Queue add/ }));

    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'AddDependency',
      source_id: 'comp_A',
      source_name: 'A',
      target_id: 'comp_C',
      target_name: 'C',
    });
  });

  it('enqueues RemoveDependency when Queue remove is clicked on an existing edge', async () => {
    mockedStructure.mockResolvedValue(makeStructure());
    mockedEnqueue.mockResolvedValue({ sequence: 2 });
    render(
      <TestQueryWrapper>
        <DependencyEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/A → B/)).toBeInTheDocument(),
    );
    await userEvent.click(
      screen.getByRole('button', { name: /Queue remove/ }),
    );
    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'RemoveDependency',
      source_id: 'comp_A',
      source_name: 'A',
      target_id: 'comp_B',
      target_name: 'B',
    });
  });

  it('disables Queue add when the proposed edge already exists', async () => {
    mockedStructure.mockResolvedValue(makeStructure());
    render(
      <TestQueryWrapper>
        <DependencyEditorPanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Queue add/ })).toBeInTheDocument(),
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/From/) as HTMLSelectElement,
      'comp_A',
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/To/) as HTMLSelectElement,
      'comp_B',
    );
    expect(screen.getByRole('button', { name: /Queue add/ })).toBeDisabled();
    expect(screen.getByText(/already exists/)).toBeInTheDocument();
  });
});
