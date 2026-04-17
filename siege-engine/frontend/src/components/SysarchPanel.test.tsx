import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { SysarchPanel } from './SysarchPanel';
import type { SysarchResponse } from '../api/sysarch';

vi.mock('../api/sysarch', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../api/sysarch')>();
  return {
    ...actual,
    getSysarch: vi.fn(),
    postFeedback: vi.fn(),
    approveDraft: vi.fn(),
    cancelGeneration: vi.fn(),
    resetSysarch: vi.fn(),
    getComponents: vi.fn(),
    getPolicies: vi.fn(),
  };
});

import * as sysarchApi from '../api/sysarch';

const mockedGet = sysarchApi.getSysarch as unknown as ReturnType<typeof vi.fn>;
const mockedPostFeedback = sysarchApi.postFeedback as unknown as ReturnType<typeof vi.fn>;
const mockedApprove = sysarchApi.approveDraft as unknown as ReturnType<typeof vi.fn>;
const mockedReset = sysarchApi.resetSysarch as unknown as ReturnType<typeof vi.fn>;

function renderPanel() {
  return render(
    <TestQueryWrapper>
      <SysarchPanel projectId="proj_1" />
    </TestQueryWrapper>
  );
}

function makeResponse(overrides: Partial<SysarchResponse> = {}): SysarchResponse {
  return {
    node: {
      id: 'sysarch_1',
      name: 'System Architecture',
      content: '',
      updated_at: '2026-04-13T00:00:00',
    },
    pending_draft: null,
    generation_status: 'idle',
    last_error: null,
    latest_telemetry: null,
    generation_started_at: null,
    current_attempt: null,
    max_attempts: null,
    ...overrides,
  };
}

const SAMPLE_DRAFT = (
  '<sysarch>' +
  '<techspec>Python + React.</techspec>' +
  '<components>' +
  '<component alias="auth">' +
  '<name>Authentication</name><kind>domain</kind>' +
  '<role>Identify callers.</role>' +
  '<api-intent>authenticate().</api-intent>' +
  '<responsibilities><resp id="resp_abc12345"/></responsibilities>' +
  '</component>' +
  '<component alias="foundation">' +
  '<name>Foundation</name><kind>domain</kind>' +
  '<role>Project root and shared utilities.</role>' +
  '<api-intent>load_settings().</api-intent>' +
  '<responsibilities><resp id="resp_def67890"/></responsibilities>' +
  '<foundation/>' +
  '</component>' +
  '</components>' +
  '<policies></policies>' +
  '<dependencies><dep from="auth" to="foundation"/></dependencies>' +
  '<domain-parent></domain-parent>' +
  '</sysarch>'
);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SysarchPanel', () => {
  it('shows a spinner while generating with no pending draft', async () => {
    mockedGet.mockResolvedValue(makeResponse({ generation_status: 'running' }));
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/Generating system architecture/i)).toBeInTheDocument()
    );
  });

  it('renders pending draft with approve and reject-regenerate buttons', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content: SAMPLE_DRAFT,
          created_at: '2026-04-13T00:00:00',
        },
      })
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText('Authentication')).toBeInTheDocument());
    expect(screen.getByText('Foundation')).toBeInTheDocument();
    // Foundation badge — identified by its title attribute
    expect(
      screen.getByTitle(/owns the root folder territory/i)
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Approve/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reject & Regenerate' })).toBeInTheDocument();
  });

  it('invokes approveDraft when Approve is clicked', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content: SAMPLE_DRAFT,
          created_at: '2026-04-13T00:00:00',
        },
      })
    );
    mockedApprove.mockResolvedValue({
      id: 'sysarch_1',
      name: 'System Architecture',
      content: 'approved',
      updated_at: '2026-04-13T00:00:00',
    });

    renderPanel();
    const btn = await screen.findByRole('button', { name: /Approve/i });
    fireEvent.click(btn);

    await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith('proj_1', 'draft_1'));
  });

  it('invokes feedback (empty) when Reject & Regenerate is clicked without feedback text', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content: SAMPLE_DRAFT,
          created_at: '2026-04-13T00:00:00',
        },
      })
    );
    mockedPostFeedback.mockResolvedValue({ job_id: 'job_1' });

    renderPanel();
    const btn = await screen.findByRole('button', { name: 'Reject & Regenerate' });
    fireEvent.click(btn);

    // The merged button calls onFeedback with empty string when no
    // feedback text is typed — the handler always uses the prior
    // draft as starting point, and empty feedback just means
    // "do-over without guidance."
    await waitFor(() => expect(mockedPostFeedback).toHaveBeenCalledWith('proj_1', ''));
  });

  it('sends typed feedback when Reject & Regenerate is clicked with feedback text', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content: SAMPLE_DRAFT,
          created_at: '2026-04-13T00:00:00',
        },
      })
    );
    mockedPostFeedback.mockResolvedValue({ job_id: 'job_1' });

    renderPanel();
    const textarea = await screen.findByPlaceholderText(/Split Billing/i);
    fireEvent.change(textarea, { target: { value: 'Split Billing into two' } });
    fireEvent.click(screen.getByRole('button', { name: 'Reject & Regenerate' }));

    await waitFor(() =>
      expect(mockedPostFeedback).toHaveBeenCalledWith('proj_1', 'Split Billing into two')
    );
  });

  it('renders approved content as read-only with reset button', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        node: {
          id: 'sysarch_1',
          name: 'System Architecture',
          content: SAMPLE_DRAFT,
          updated_at: '2026-04-13T00:00:00',
        },
      })
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText('Authentication')).toBeInTheDocument());
    expect(screen.getByText(/Approved · read-only/i)).toBeInTheDocument();
    // The sysarch panel wires onReset, so the reset button should be visible.
    expect(screen.getByRole('button', { name: /Reset & Regenerate/i })).toBeInTheDocument();
  });

  it('reset button requires two-click confirm', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        node: {
          id: 'sysarch_1',
          name: 'System Architecture',
          content: SAMPLE_DRAFT,
          updated_at: '2026-04-13T00:00:00',
        },
      })
    );
    mockedReset.mockResolvedValue({
      ok: true,
      nodes_deleted: 5,
      drafts_discarded: 1,
      jobs_cancelled: 2,
    });

    renderPanel();
    // First click: the button text changes to the confirm prompt.
    const resetBtn = await screen.findByRole('button', { name: /Reset & Regenerate/i });
    fireEvent.click(resetBtn);
    expect(screen.getByRole('button', { name: /Confirm reset/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Cancel/i })).toBeInTheDocument();

    // Second click: actually fires the reset.
    fireEvent.click(screen.getByRole('button', { name: /Confirm reset/i }));
    await waitFor(() => expect(mockedReset).toHaveBeenCalledWith('proj_1'));
  });

  it('shows an error banner with Retry when generation failed and no content', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        generation_status: 'failed',
        last_error: 'parse error',
      })
    );
    mockedPostFeedback.mockResolvedValue({ job_id: 'job_retry' });
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText(/Generation failed/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/parse error/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Retry/i }));
    await waitFor(() => expect(mockedPostFeedback).toHaveBeenCalledWith('proj_1', ''));
  });
});
