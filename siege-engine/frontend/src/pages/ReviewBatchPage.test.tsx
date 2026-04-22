import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ReviewBatchPage } from './ReviewBatchPage';

vi.mock('../api/review', () => ({
  getReviewBatch: vi.fn(),
  listReviewBatchNodes: vi.fn(),
  getReviewBatchNodeDiff: vi.fn(),
  closeReviewBatch: vi.fn(),
  openReviewBatch: vi.fn(),
}));

import * as reviewApi from '../api/review';

const mockedGetBatch = reviewApi.getReviewBatch as unknown as ReturnType<
  typeof vi.fn
>;
const mockedListNodes = reviewApi.listReviewBatchNodes as unknown as ReturnType<
  typeof vi.fn
>;
const mockedGetDiff = reviewApi.getReviewBatchNodeDiff as unknown as ReturnType<
  typeof vi.fn
>;
const mockedClose = reviewApi.closeReviewBatch as unknown as ReturnType<
  typeof vi.fn
>;

function renderPage() {
  return render(
    <TestQueryWrapper>
      <MemoryRouter initialEntries={['/projects/proj_1/review/batch_abc']}>
        <Routes>
          <Route
            path="/projects/:id/review/:batchId"
            element={<ReviewBatchPage />}
          />
          <Route
            path="/projects/:id"
            element={<div>Workspace</div>}
          />
        </Routes>
      </MemoryRouter>
    </TestQueryWrapper>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedGetBatch.mockResolvedValue({
    id: 'batch_abc',
    project_id: 'proj_1',
    pinned_offset: 7,
    created_at: '2026-04-22T00:00:00',
    closed_at: null,
  });
});

describe('ReviewBatchPage', () => {
  it('renders the header with the pinned offset + node count', async () => {
    mockedListNodes.mockResolvedValue([]);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/pinned @ offset 7/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/0 stale nodes/)).toBeInTheDocument();
    expect(
      screen.getByText(/Nothing stale in this batch/i),
    ).toBeInTheDocument();
  });

  it('lists stale nodes in the left rail with tier + reasons', async () => {
    mockedListNodes.mockResolvedValue([
      {
        node_id: 'comp_AAAA1111',
        tier: 'comp',
        name: 'Auth',
        parent_id: null,
        reasons: ['content_changed'],
        is_destructive: false,
        topological_order: 50,
      },
      {
        node_id: 'feat_FFFFFFFF',
        tier: 'feat',
        name: 'Login',
        parent_id: null,
        reasons: ['structural_change'],
        is_destructive: true,
        topological_order: 10,
      },
    ]);
    mockedGetDiff.mockResolvedValue({
      node_content: { before: 'Auth was', after: 'Auth now' },
      fragments: [],
    });

    renderPage();
    await waitFor(() => expect(screen.getByText('Auth')).toBeInTheDocument());
    expect(screen.getByText('Login')).toBeInTheDocument();
    expect(screen.getByText(/content_changed/)).toBeInTheDocument();
    expect(screen.getByText(/structural_change/)).toBeInTheDocument();
  });

  it('renders the diff pane for the first stale node by default', async () => {
    mockedListNodes.mockResolvedValue([
      {
        node_id: 'comp_AAAA1111',
        tier: 'comp',
        name: 'Auth',
        parent_id: null,
        reasons: ['content_changed'],
        is_destructive: false,
        topological_order: 50,
      },
    ]);
    mockedGetDiff.mockResolvedValue({
      node_content: {
        before: 'Auth content v1.',
        after: 'Auth content v2.',
      },
      fragments: [
        {
          fragment_kind: 'techspec',
          before: 'old techspec',
          after: 'new techspec',
        },
      ],
    });

    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/old techspec/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/new techspec/)).toBeInTheDocument();
    // Fragment accordion header — there's only one <code> per
    // fragment summary.
    expect(screen.getByText('techspec').tagName).toBe('CODE');
  });

  it('calls the close mutation when Close batch is clicked', async () => {
    mockedListNodes.mockResolvedValue([]);
    mockedClose.mockResolvedValue({
      id: 'batch_abc',
      project_id: 'proj_1',
      pinned_offset: 7,
      created_at: '2026-04-22T00:00:00',
      closed_at: '2026-04-22T01:00:00',
    });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /Close batch/i }),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: /Close batch/i }));
    await waitFor(() =>
      expect(mockedClose).toHaveBeenCalledWith('proj_1', 'batch_abc'),
    );
  });
});
