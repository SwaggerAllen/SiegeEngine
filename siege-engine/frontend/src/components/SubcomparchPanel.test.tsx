import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { SubcomparchPanel } from './SubcomparchPanel';
import type { SubcomparchResponse } from '../api/subcomparch';

vi.mock('../api/subcomparch', () => ({
  getSubcomparch: vi.fn(),
  postFeedback: vi.fn(),
  approveDraft: vi.fn(),
  discardDraft: vi.fn(),
}));

import * as subcomparchApi from '../api/subcomparch';

const mockedGet = subcomparchApi.getSubcomparch as unknown as ReturnType<typeof vi.fn>;
const mockedPostFeedback =
  subcomparchApi.postFeedback as unknown as ReturnType<typeof vi.fn>;
const mockedApprove =
  subcomparchApi.approveDraft as unknown as ReturnType<typeof vi.fn>;
const mockedDiscard =
  subcomparchApi.discardDraft as unknown as ReturnType<typeof vi.fn>;

function renderPanel() {
  return render(
    <TestQueryWrapper>
      <SubcomparchPanel
        projectId="proj_1"
        parentCompId="comp_billing1"
        subId="comp_token_sto"
        subName="TokenStore"
      />
    </TestQueryWrapper>
  );
}

function makeResponse(
  overrides: Partial<SubcomparchResponse> = {}
): SubcomparchResponse {
  return {
    node: {
      id: 'comp_token_sto',
      name: 'TokenStore',
      parent_id: 'comp_billing1',
      content: '',
      updated_at: '2026-04-13T00:00:00',
    },
    pending_draft: null,
    generation_status: 'idle',
    last_error: null,
    latest_telemetry: null,
    ...overrides,
  };
}

const SAMPLE_DRAFT =
  '<subcomparch>' +
  '<technical-specification>Real techspec for tokenization.</technical-specification>' +
  '<public-surface>tokenize(raw) -> Token.</public-surface>' +
  '<private-surface>_rotate_keys(cutoff).</private-surface>' +
  '<dependencies>' +
  '<dep to="foundation"/>' +
  '<dep to="comp_audit9999"/>' +
  '</dependencies>' +
  '</subcomparch>';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SubcomparchPanel', () => {
  it('shows spinner while generating', async () => {
    mockedGet.mockResolvedValue(makeResponse({ generation_status: 'running' }));
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(/Generating TokenStore architecture doc/i)
      ).toBeInTheDocument()
    );
  });

  it('renders pending draft with four sections and distinct dep styling', async () => {
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
      expect(screen.getByText(/Real techspec for tokenization/)).toBeInTheDocument()
    );
    expect(screen.getByText(/tokenize\(raw\) -> Token/)).toBeInTheDocument();
    expect(screen.getByText(/_rotate_keys\(cutoff\)/)).toBeInTheDocument();
    // Dep sections render aliases under one subheader and comp_ IDs
    // under another.
    expect(screen.getByText('Same-parent siblings')).toBeInTheDocument();
    expect(screen.getByText('Parent-sibling components')).toBeInTheDocument();
    expect(screen.getByText('foundation')).toBeInTheDocument();
    expect(screen.getByText('comp_audit9999')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Approve/i })).toBeInTheDocument();
  });

  it('invokes approveDraft scoped to (projectId, parentCompId, subId)', async () => {
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
      id: 'comp_token_sto',
      name: 'TokenStore',
      parent_id: 'comp_billing1',
      content: 'approved',
      updated_at: '2026-04-13T00:00:00',
    });
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: /Approve/i }));
    await waitFor(() =>
      expect(mockedApprove).toHaveBeenCalledWith(
        'proj_1',
        'comp_billing1',
        'comp_token_sto',
        'draft_1'
      )
    );
  });

  it('sends feedback scoped to the (parent, sub) pair', async () => {
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
    const textarea = await screen.findByPlaceholderText(/Narrow the public surface/i);
    fireEvent.change(textarea, { target: { value: 'Tighten rotation' } });
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }));
    await waitFor(() =>
      expect(mockedPostFeedback).toHaveBeenCalledWith(
        'proj_1',
        'comp_billing1',
        'comp_token_sto',
        'Tighten rotation'
      )
    );
  });

  it('discards with (projectId, parentCompId, subId) context', async () => {
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
    fireEvent.click(
      await screen.findByRole('button', { name: 'Reject & Regenerate' })
    );
    await waitFor(() =>
      expect(mockedDiscard).toHaveBeenCalledWith(
        'proj_1',
        'comp_billing1',
        'comp_token_sto',
        'draft_1'
      )
    );
  });

  it('shows read-only explanation after approval', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        node: {
          id: 'comp_token_sto',
          name: 'TokenStore',
          parent_id: 'comp_billing1',
          content: SAMPLE_DRAFT,
          updated_at: '2026-04-13T00:00:00',
        },
      })
    );
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/Approved · read-only/i)).toBeInTheDocument()
    );
    // readOnlyExplanation caption from makeLabels
    expect(
      screen.getByText(/anchor for its impl node/i)
    ).toBeInTheDocument();
  });
});
