import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { RequirementsPanel } from './RequirementsPanel';
import type { ReqsResponse } from '../api/requirements';

// Mock the API module so we can drive component state from tests.
vi.mock('../api/requirements', () => ({
  getRequirements: vi.fn(),
  postFeedback: vi.fn(),
  approveDraft: vi.fn(),
  cancelGeneration: vi.fn(),
  getResponsibilities: vi.fn(),
}));

import * as reqsApi from '../api/requirements';

const mockedGet = reqsApi.getRequirements as unknown as ReturnType<typeof vi.fn>;
const mockedPostFeedback = reqsApi.postFeedback as unknown as ReturnType<typeof vi.fn>;
const mockedApprove = reqsApi.approveDraft as unknown as ReturnType<typeof vi.fn>;

function renderPanel() {
  return render(
    <TestQueryWrapper>
      <RequirementsPanel projectId="proj_1" />
    </TestQueryWrapper>
  );
}

function makeResponse(overrides: Partial<ReqsResponse> = {}): ReqsResponse {
  return {
    node: {
      id: 'reqs_1',
      name: 'Requirements',
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
      failed_raw_output: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('RequirementsPanel', () => {
  it('shows a spinner while generating with no pending draft', async () => {
    mockedGet.mockResolvedValue(makeResponse({ generation_status: 'running' }));
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/Generating requirements/i)).toBeInTheDocument()
    );
  });

  it('renders pending draft with approve/discard/regenerate actions', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content:
            '<requirements><responsibility><name>Auth</name><intent>Identify users.</intent></responsibility></requirements>',
          created_at: '2026-04-13T00:00:00',
        },
      })
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText('Auth')).toBeInTheDocument());
    expect(screen.getByText('Identify users.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Approve/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reject & Regenerate' })).toBeInTheDocument();
  });

  it('invokes approveDraft when Approve is clicked', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content:
            '<requirements><responsibility><name>A</name><intent>Ok.</intent></responsibility></requirements>',
          created_at: '2026-04-13T00:00:00',
        },
      })
    );
    mockedApprove.mockResolvedValue({
      id: 'reqs_1',
      name: 'Requirements',
      content: 'approved',
      updated_at: '2026-04-13T00:00:00',
    });

    renderPanel();
    const btn = await screen.findByRole('button', { name: /Approve/i });
    fireEvent.click(btn);

    await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith('proj_1', 'draft_1'));
  });

  it('invokes feedback (empty) when Reject & Regenerate is clicked without feedback', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content:
            '<requirements><responsibility><name>A</name><intent>Ok.</intent></responsibility></requirements>',
          created_at: '2026-04-13T00:00:00',
        },
      })
    );
    mockedPostFeedback.mockResolvedValue({ job_id: 'job_1' });

    renderPanel();
    const btn = await screen.findByRole('button', { name: 'Reject & Regenerate' });
    fireEvent.click(btn);

    await waitFor(() => expect(mockedPostFeedback).toHaveBeenCalledWith('proj_1', ''));
  });

  it('sends feedback to postFeedback when Reject & Regenerate is clicked with feedback', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content:
            '<requirements><responsibility><name>A</name><intent>Ok.</intent></responsibility></requirements>',
          created_at: '2026-04-13T00:00:00',
        },
      })
    );
    mockedPostFeedback.mockResolvedValue({ job_id: 'job_1' });

    renderPanel();
    const textarea = await screen.findByPlaceholderText(/Add rate limiting/i);
    fireEvent.change(textarea, { target: { value: 'Add rate limiting' } });
    fireEvent.click(screen.getByRole('button', { name: 'Reject & Regenerate' }));

    await waitFor(() =>
      expect(mockedPostFeedback).toHaveBeenCalledWith('proj_1', 'Add rate limiting')
    );
  });

  it('renders approved content as read-only', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        node: {
          id: 'reqs_1',
          name: 'Requirements',
          content:
            '<requirements><responsibility><name>Final</name><intent>Final intent.</intent></responsibility></requirements>',
          updated_at: '2026-04-13T00:00:00',
        },
      })
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText('Final')).toBeInTheDocument());
    expect(screen.getByText(/Approved · read-only/i)).toBeInTheDocument();
  });

  it('shows an error banner with Retry when generation failed and no content', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        generation_status: 'failed',
        last_error: 'timeout after 900s',
      })
    );
    mockedPostFeedback.mockResolvedValue({ job_id: 'job_retry' });
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText(/Generation failed/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/timeout after 900s/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Retry/i }));
    await waitFor(() => expect(mockedPostFeedback).toHaveBeenCalledWith('proj_1', ''));
  });
});
