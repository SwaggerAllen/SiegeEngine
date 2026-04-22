import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ImplResponse } from '../api/impl';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ImplPanel } from './ImplPanel';

// Mock both API functions on the impl module. The ImplPanel
// branches on `kind` to pick which hook runs, which in turn
// picks which mocked function gets called.
vi.mock('../api/impl', async () => {
  const actual = await vi.importActual<typeof import('../api/impl')>('../api/impl');
  return {
    ...actual,
    getImplTopLevel: vi.fn(),
    getImplSub: vi.fn(),
    postImplTopLevelFeedback: vi.fn(),
    postImplSubFeedback: vi.fn(),
    approveImplTopLevelDraft: vi.fn(),
    approveImplSubDraft: vi.fn(),
    discardImplTopLevelDraft: vi.fn(),
    discardImplSubDraft: vi.fn(),
    cancelImplTopLevelGeneration: vi.fn(),
    cancelImplSubGeneration: vi.fn(),
  };
});

import * as implApi from '../api/impl';

const mockedGetTopLevel = implApi.getImplTopLevel as unknown as ReturnType<typeof vi.fn>;
const mockedGetSub = implApi.getImplSub as unknown as ReturnType<typeof vi.fn>;
const mockedApproveTopLevel =
  implApi.approveImplTopLevelDraft as unknown as ReturnType<typeof vi.fn>;

function response(overrides: Partial<ImplResponse> = {}): ImplResponse {
  return {
    node: {
      id: 'impl_AAAAAAAA',
      name: 'TopComp impl',
      parent_id: 'comp_BBBBBBBB',
      content: '',
      updated_at: '2026-04-17T00:00:00',
    },
    pending_draft: null,
    previous_draft_content: null,
    auto_revision_intermediates: [],
    generation_status: 'idle',
    last_error: null,
    latest_telemetry: null,
    generation_started_at: null,
    current_attempt: null,
    max_attempts: null,
    failed_raw_output: null,
    review_text: '',
    review_status: 'idle',
    review_last_error: null,
    review_started_at: null,
    review_current_attempt: null,
    review_max_attempts: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ImplPanel top-level', () => {
  it('renders the pending draft with approve + regenerate actions', async () => {
    mockedGetTopLevel.mockResolvedValue(
      response({
        pending_draft: {
          id: 'draft_1',
          content:
            '<implementation><behavior>B</behavior>' +
            '<invariants>I</invariants><sequencing>S</sequencing>' +
            '<edge-cases>E</edge-cases></implementation>',
          created_at: '2026-04-17T00:00:00',
        },
      }),
    );
    render(
      <TestQueryWrapper>
        <ImplPanel
          kind="top-level"
          projectId="proj_1"
          compId="comp_BBBBBBBB"
          ownerName="TopComp"
        />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Approve/i })).toBeInTheDocument(),
    );
  });

  it('approves a draft via the top-level approve mutation', async () => {
    mockedGetTopLevel.mockResolvedValue(
      response({
        pending_draft: {
          id: 'draft_x',
          content:
            '<implementation><behavior>B</behavior>' +
            '<invariants>I</invariants><sequencing>S</sequencing>' +
            '<edge-cases>E</edge-cases></implementation>',
          created_at: '2026-04-17T00:00:00',
        },
      }),
    );
    mockedApproveTopLevel.mockResolvedValue(undefined);

    render(
      <TestQueryWrapper>
        <ImplPanel
          kind="top-level"
          projectId="proj_1"
          compId="comp_BBBBBBBB"
          ownerName="TopComp"
        />
      </TestQueryWrapper>,
    );
    const btn = await screen.findByRole('button', { name: /Approve/i });
    await userEvent.click(btn);
    await waitFor(() =>
      expect(mockedApproveTopLevel).toHaveBeenCalledWith(
        'proj_1',
        'comp_BBBBBBBB',
        'draft_x',
      ),
    );
  });
});

describe('ImplPanel sub', () => {
  it('uses the sub API for a per-subcomponent impl', async () => {
    mockedGetSub.mockResolvedValue(
      response({
        node: {
          id: 'impl_S',
          name: 'Sub impl',
          parent_id: 'comp_SSSSSSSS',
          content: '',
          updated_at: '2026-04-17T00:00:00',
        },
      }),
    );
    render(
      <TestQueryWrapper>
        <ImplPanel
          kind="sub"
          projectId="proj_1"
          parentCompId="comp_PARENTID"
          subId="comp_SSSSSSSS"
          ownerName="Sub"
        />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(mockedGetSub).toHaveBeenCalledWith(
        'proj_1',
        'comp_PARENTID',
        'comp_SSSSSSSS',
      ),
    );
  });
});
