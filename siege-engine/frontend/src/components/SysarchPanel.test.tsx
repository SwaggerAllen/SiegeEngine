import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { SysarchPanel } from './SysarchPanel';
import type { SysarchResponse } from '../api/sysarch';

vi.mock('../api/sysarch', () => ({
  getSysarch: vi.fn(),
  postFeedback: vi.fn(),
  approveDraft: vi.fn(),
  discardDraft: vi.fn(),
  cancelGeneration: vi.fn(),
  getComponents: vi.fn(),
  getPolicies: vi.fn(),
}));

import * as sysarchApi from '../api/sysarch';

const mockedGet = sysarchApi.getSysarch as unknown as ReturnType<typeof vi.fn>;
const mockedPostFeedback = sysarchApi.postFeedback as unknown as ReturnType<typeof vi.fn>;
const mockedApprove = sysarchApi.approveDraft as unknown as ReturnType<typeof vi.fn>;
const mockedDiscard = sysarchApi.discardDraft as unknown as ReturnType<typeof vi.fn>;

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

  it('renders pending draft with approve/discard/regenerate actions', async () => {
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
    expect(screen.getByRole('button', { name: 'Regenerate' })).toBeDisabled();
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

  it('invokes discardDraft when Reject & Regenerate is clicked', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content: SAMPLE_DRAFT,
          created_at: '2026-04-13T00:00:00',
        },
      })
    );
    mockedDiscard.mockResolvedValue(undefined);

    renderPanel();
    const btn = await screen.findByRole('button', { name: 'Reject & Regenerate' });
    fireEvent.click(btn);

    await waitFor(() => expect(mockedDiscard).toHaveBeenCalledWith('proj_1', 'draft_1'));
  });

  it('sends feedback when Regenerate is clicked', async () => {
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
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }));

    await waitFor(() =>
      expect(mockedPostFeedback).toHaveBeenCalledWith('proj_1', 'Split Billing into two')
    );
  });

  it('renders approved content as read-only', async () => {
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
