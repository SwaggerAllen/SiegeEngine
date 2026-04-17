import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { SubreqsPanel } from './SubreqsPanel';
import type { SubreqsResponse } from '../api/subreqs';

vi.mock('../api/subreqs', () => ({
  getSubreqs: vi.fn(),
  postFeedback: vi.fn(),
  approveDraft: vi.fn(),
  cancelGeneration: vi.fn(),
  getSubresponsibilities: vi.fn(),
}));

import * as subreqsApi from '../api/subreqs';

const mockedGet = subreqsApi.getSubreqs as unknown as ReturnType<typeof vi.fn>;
const mockedPostFeedback = subreqsApi.postFeedback as unknown as ReturnType<typeof vi.fn>;
const mockedApprove = subreqsApi.approveDraft as unknown as ReturnType<typeof vi.fn>;

function renderPanel() {
  return render(
    <TestQueryWrapper>
      <SubreqsPanel
        projectId="proj_1"
        componentId="comp_billing1"
        componentName="Billing Service"
      />
    </TestQueryWrapper>
  );
}

function makeResponse(overrides: Partial<SubreqsResponse> = {}): SubreqsResponse {
  return {
    node: {
      id: 'subreqs_1',
      name: 'Subrequirements',
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
  '<subrequirements>' +
  '<subresponsibility>' +
  '<name>Card Tokenization</name>' +
  '<intent>Convert raw cards to tokens.</intent>' +
  '<derived-from><resp id="resp_parent01"/></derived-from>' +
  '</subresponsibility>' +
  '</subrequirements>'
);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SubreqsPanel', () => {
  it('shows spinner while generating', async () => {
    mockedGet.mockResolvedValue(makeResponse({ generation_status: 'running' }));
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(/Generating Billing Service subrequirements/i)
      ).toBeInTheDocument()
    );
  });

  it('renders pending draft with action buttons', async () => {
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
    await waitFor(() =>
      expect(screen.getByText('Card Tokenization')).toBeInTheDocument()
    );
    expect(screen.getByText('resp_parent01')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Approve/i })).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Reject & Regenerate' })
    ).toBeInTheDocument();
  });

  it('invokes approveDraft with componentId context', async () => {
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
      id: 'subreqs_1',
      name: 'Subrequirements',
      content: 'approved',
      updated_at: '2026-04-13T00:00:00',
    });
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: /Approve/i }));
    await waitFor(() =>
      expect(mockedApprove).toHaveBeenCalledWith('proj_1', 'comp_billing1', 'draft_1')
    );
  });

  it('sends feedback scoped to the component', async () => {
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
    const textarea = await screen.findByPlaceholderText(/retry backoff/i);
    fireEvent.change(textarea, { target: { value: 'Add backoff' } });
    fireEvent.click(screen.getByRole('button', { name: 'Reject & Regenerate' }));
    await waitFor(() =>
      expect(mockedPostFeedback).toHaveBeenCalledWith(
        'proj_1',
        'comp_billing1',
        'Add backoff'
      )
    );
  });

  it('rejects with empty feedback scoped to the component', async () => {
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
    fireEvent.click(await screen.findByRole('button', { name: 'Reject & Regenerate' }));
    await waitFor(() =>
      expect(mockedPostFeedback).toHaveBeenCalledWith('proj_1', 'comp_billing1', '')
    );
  });
});
