import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { SysarchPanel } from './SysarchPanel';
import type { BodyResponse, ScopeStateResponse } from '../api/siege';

vi.mock('../api/siege', () => ({
  getScopeState: vi.fn(),
  getBody: vi.fn(),
}));

import * as siegeApi from '../api/siege';

const mockedGetState = siegeApi.getScopeState as unknown as ReturnType<typeof vi.fn>;
const mockedGetBody = siegeApi.getBody as unknown as ReturnType<typeof vi.fn>;

function renderPanel() {
  return render(
    <TestQueryWrapper>
      <SysarchPanel projectId="proj_1" />
    </TestQueryWrapper>,
  );
}

function stateResponse(overrides: Partial<ScopeStateResponse> = {}): ScopeStateResponse {
  return {
    ref: 'main',
    ref_head_sha: 'deadbeef',
    found: true,
    status: 'absent',
    ...overrides,
  };
}

function bodyResponse(body_text: string): BodyResponse {
  return {
    ref: 'main',
    ref_head_sha: 'deadbeef',
    found: true,
    body_path: 'sysarch/proj/body.md',
    body_text,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SysarchPanel', () => {
  it('shows the absent state with a draft hint', async () => {
    mockedGetState.mockResolvedValue(stateResponse({ found: true, status: 'absent' }));
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/No substrate state/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/\/draft-sysarch proj/)).toBeInTheDocument();
  });

  it('renders the draft body when status=drafted', async () => {
    mockedGetState.mockResolvedValue(
      stateResponse({ status: 'drafted', draft: { body_path: 'p', body_sha256: 'x', generated_at: 't' } }),
    );
    mockedGetBody.mockResolvedValue(bodyResponse('<sysarch>hello</sysarch>'));
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId('body-draft')).toHaveTextContent('<sysarch>hello</sysarch>'),
    );
    expect(screen.getByText(/\/review-sysarch proj/)).toBeInTheDocument();
  });

  it('renders both draft and review bodies when status=reviewed', async () => {
    mockedGetState.mockResolvedValue(
      stateResponse({
        status: 'reviewed',
        draft: { body_path: 'p', body_sha256: 'x', generated_at: 't' },
        review: { body_path: 'r', body_sha256: 'y', reviewed_at: 't', score: 75 },
      }),
    );
    mockedGetBody.mockImplementation(
      (_p: string, _scope: unknown, _ref: string, which: 'draft' | 'review') =>
        Promise.resolve(bodyResponse(which === 'review' ? 'REVIEW' : 'DRAFT')),
    );
    renderPanel();
    await waitFor(() => expect(screen.getByTestId('body-draft')).toHaveTextContent('DRAFT'));
    expect(screen.getByTestId('body-review')).toHaveTextContent('REVIEW');
    expect(screen.getByText(/Review score:/i)).toBeInTheDocument();
  });
});
