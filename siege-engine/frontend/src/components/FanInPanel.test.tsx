import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { FanInResponse } from '../api/fanin';
import { TestQueryWrapper } from '../test/queryWrapper';
import { FanInPanel } from './FanInPanel';

vi.mock('../api/fanin', async () => {
  const actual = await vi.importActual<typeof import('../api/fanin')>('../api/fanin');
  return {
    ...actual,
    getFanIn: vi.fn(),
    regenerateFanIn: vi.fn(),
    cancelFanIn: vi.fn(),
  };
});

import * as faninApi from '../api/fanin';

const mockedGet = faninApi.getFanIn as unknown as ReturnType<typeof vi.fn>;
const mockedRegenerate = faninApi.regenerateFanIn as unknown as ReturnType<typeof vi.fn>;
const mockedCancel = faninApi.cancelFanIn as unknown as ReturnType<typeof vi.fn>;

function response(overrides: Partial<FanInResponse> = {}): FanInResponse {
  return {
    node: {
      id: 'fanin_AAAAAAAA',
      name: 'Billing fan-in',
      owner_comp_id: 'comp_BBBBBBBB',
      content: '',
      updated_at: '2026-04-17T00:00:00',
    },
    generation_status: 'idle',
    last_error: null,
    latest_telemetry: null,
    generation_started_at: null,
    current_attempt: null,
    max_attempts: null,
    failed_raw_output: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FanInPanel', () => {
  it('renders empty-shell message when content is blank', async () => {
    mockedGet.mockResolvedValue(response());
    render(
      <TestQueryWrapper>
        <FanInPanel projectId="proj_1" compId="comp_BBBBBBBB" ownerName="Billing" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/No fan-in content yet/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: /Regenerate/i })).toBeInTheDocument();
  });

  it('renders the fan-in XML sections when content is present', async () => {
    mockedGet.mockResolvedValue(
      response({
        node: {
          id: 'fanin_AAAAAAAA',
          name: 'Billing fan-in',
          owner_comp_id: 'comp_BBBBBBBB',
          content:
            '<fanin><summary>Billing as built.</summary>' +
            '<exposed-surface>pay / refund</exposed-surface>' +
            '<realized-behavior>strict ordering</realized-behavior></fanin>',
          updated_at: '2026-04-17T00:00:00',
        },
      }),
    );
    render(
      <TestQueryWrapper>
        <FanInPanel projectId="proj_1" compId="comp_BBBBBBBB" ownerName="Billing" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Billing as built\./)).toBeInTheDocument(),
    );
    // All three section headers render.
    expect(screen.getByText(/^Summary$/)).toBeInTheDocument();
    expect(screen.getByText(/Exposed Surface/)).toBeInTheDocument();
    expect(screen.getByText(/Realized Behavior/)).toBeInTheDocument();
  });

  it('invokes regenerate on click', async () => {
    mockedGet.mockResolvedValue(response());
    mockedRegenerate.mockResolvedValue({ job_id: 'job_1' });
    render(
      <TestQueryWrapper>
        <FanInPanel projectId="proj_1" compId="comp_BBBBBBBB" ownerName="Billing" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Regenerate/i })).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole('button', { name: /Regenerate/i }));
    expect(mockedRegenerate).toHaveBeenCalledWith('proj_1', 'comp_BBBBBBBB');
  });

  it('shows Stop button while generation is running', async () => {
    mockedGet.mockResolvedValue(
      response({
        generation_status: 'running',
        generation_started_at: '2026-04-17T00:00:00',
        current_attempt: 2,
        max_attempts: 3,
      }),
    );
    mockedCancel.mockResolvedValue({ cancelled: true });
    render(
      <TestQueryWrapper>
        <FanInPanel projectId="proj_1" compId="comp_BBBBBBBB" ownerName="Billing" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Stop/i })).toBeInTheDocument(),
    );
    // No Regenerate button while running.
    expect(screen.queryByRole('button', { name: /Regenerate/i })).toBeNull();
    // Attempt counter visible.
    expect(screen.getByText(/Attempt 2 \/ 3/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Stop/i }));
    expect(mockedCancel).toHaveBeenCalledWith('proj_1', 'comp_BBBBBBBB');
  });

  it('renders last_error block when the last attempt failed', async () => {
    mockedGet.mockResolvedValue(
      response({
        generation_status: 'failed',
        last_error: 'Parse retries exhausted',
      }),
    );
    render(
      <TestQueryWrapper>
        <FanInPanel projectId="proj_1" compId="comp_BBBBBBBB" ownerName="Billing" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Last generation failed/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/Parse retries exhausted/)).toBeInTheDocument();
  });
});
