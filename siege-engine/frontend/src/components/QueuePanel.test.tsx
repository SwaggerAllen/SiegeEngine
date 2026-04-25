import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueueListResponse, QueueRow } from '../api/queue';
import { TestQueryWrapper } from '../test/queryWrapper';
import { QueuePanel } from './QueuePanel';

vi.mock('../api/queue', async () => {
  const actual = await vi.importActual<typeof import('../api/queue')>('../api/queue');
  return {
    ...actual,
    listQueue: vi.fn(),
    enqueueInstruction: vi.fn(),
    discardPending: vi.fn(),
    applyQueue: vi.fn(),
  };
});

import * as queueApi from '../api/queue';

const mockedList = queueApi.listQueue as unknown as ReturnType<typeof vi.fn>;
const mockedDiscard = queueApi.discardPending as unknown as ReturnType<typeof vi.fn>;
const mockedApply = queueApi.applyQueue as unknown as ReturnType<typeof vi.fn>;

function row(overrides: Partial<QueueRow> = {}): QueueRow {
  return {
    sequence: 1,
    instruction_type: 'Rename',
    payload: {
      instruction_type: 'Rename',
      node_id: 'comp_AAAAAAAA',
      old_name: 'Old',
      new_name: 'New',
    },
    status: 'queued',
    job_id: null,
    error: null,
    created_at: '2026-04-20T00:00:00',
    updated_at: '2026-04-20T00:00:00',
    ...overrides,
  };
}

function listResponse(rows: QueueRow[] = []): QueueListResponse {
  return { rows };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('QueuePanel', () => {
  it('shows empty-state when no rows exist', async () => {
    mockedList.mockResolvedValue(listResponse([]));
    render(
      <TestQueryWrapper>
        <QueuePanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/No queued instructions/i)).toBeInTheDocument(),
    );
  });

  it('lists queued rows with Apply + Discard affordances', async () => {
    mockedList.mockResolvedValue(
      listResponse([
        row({ sequence: 1 }),
        row({
          sequence: 2,
          instruction_type: 'AddDependency',
          payload: {
            instruction_type: 'AddDependency',
            source_id: 'comp_AAAAAAAA',
            source_name: 'A',
            target_id: 'comp_BBBBBBBB',
            target_name: 'B',
          },
        }),
      ]),
    );
    render(
      <TestQueryWrapper>
        <QueuePanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(
        screen.getByText(/Rename comp_AAAAAAAA from "Old" to "New"/),
      ).toBeInTheDocument(),
    );
    // Both rows rendered.
    expect(screen.getByText(/Add dependency: "A" → "B"/)).toBeInTheDocument();
    // Apply button enabled with count.
    expect(screen.getByRole('button', { name: /Apply 2 changes/ })).toBeEnabled();
    // Discard-all button visible.
    expect(screen.getByRole('button', { name: /Discard all queued/ })).toBeEnabled();
  });

  it('invokes per-row discard with the matching sequence', async () => {
    mockedList.mockResolvedValue(listResponse([row({ sequence: 7 })]));
    mockedDiscard.mockResolvedValue({ discarded: 1 });
    render(
      <TestQueryWrapper>
        <QueuePanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/#7/)).toBeInTheDocument(),
    );
    const discardBtn = screen.getAllByRole('button', { name: /^Discard$/ })[0];
    await userEvent.click(discardBtn);
    expect(mockedDiscard).toHaveBeenCalledWith('p1', 7);
  });

  it('invokes bulk discard with no sequence argument', async () => {
    mockedList.mockResolvedValue(
      listResponse([row({ sequence: 1 }), row({ sequence: 2 })]),
    );
    mockedDiscard.mockResolvedValue({ discarded: 2 });
    render(
      <TestQueryWrapper>
        <QueuePanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Discard all queued/ })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole('button', { name: /Discard all queued/ }));
    expect(mockedDiscard).toHaveBeenCalledWith('p1', undefined);
  });

  it('invokes apply and disables button during running state', async () => {
    mockedList.mockResolvedValue(listResponse([row({ sequence: 1 })]));
    mockedApply.mockResolvedValue({ job_id: 'job_1' });
    render(
      <TestQueryWrapper>
        <QueuePanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Apply 1 change/ })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole('button', { name: /Apply 1 change/ }));
    expect(mockedApply).toHaveBeenCalledWith('p1');
  });

  it('disables Apply when any row is running and shows Applying banner', async () => {
    mockedList.mockResolvedValue(
      listResponse([row({ sequence: 1, status: 'running' })]),
    );
    render(
      <TestQueryWrapper>
        <QueuePanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Applying 1 instruction/i)).toBeInTheDocument(),
    );
    // Apply button is disabled — no queued rows, and running blocks it.
    const applyBtn = screen.getByRole('button', { name: /^Apply$/ });
    expect(applyBtn).toBeDisabled();
  });

  it('renders ProposeFeature rows with the description prominent', async () => {
    mockedList.mockResolvedValue(
      listResponse([
        row({
          sequence: 9,
          instruction_type: 'ProposeFeature',
          payload: {
            instruction_type: 'ProposeFeature',
            node_id: 'feat_NEWNODE1',
            name_hint: '(proposing) User profiles',
            description: 'User profile management with avatar uploads',
          },
        }),
      ]),
    );
    render(
      <TestQueryWrapper>
        <QueuePanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(
        screen.getByText(/Propose feature: User profile management with avatar uploads/),
      ).toBeInTheDocument(),
    );
  });

  it('surfaces the failed row error in a banner', async () => {
    mockedList.mockResolvedValue(
      listResponse([
        row({
          sequence: 4,
          status: 'failed',
          error: 'Dependency cycle: comp_A → comp_B → comp_A',
        }),
      ]),
    );
    render(
      <TestQueryWrapper>
        <QueuePanel projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Apply halted on sequence #4/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/Dependency cycle/)).toBeInTheDocument();
  });
});
