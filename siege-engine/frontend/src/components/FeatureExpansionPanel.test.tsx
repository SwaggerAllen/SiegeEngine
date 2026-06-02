import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { FeatureExpansionPanel } from './FeatureExpansionPanel';
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
      <FeatureExpansionPanel projectId="proj_1" />
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
    body_path: 'feature_expansion/proj/body.md',
    body_text,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FeatureExpansionPanel', () => {
  it('shows the absent state with a draft hint', async () => {
    mockedGetState.mockResolvedValue(stateResponse());
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/No substrate state/i)).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/\/draft-feature-expansion proj/),
    ).toBeInTheDocument();
  });

  it('renders the draft body when status=drafted', async () => {
    mockedGetState.mockResolvedValue(
      stateResponse({
        status: 'drafted',
        draft: { body_path: 'p', body_sha256: 'x', generated_at: 't' },
      }),
    );
    mockedGetBody.mockResolvedValue(bodyResponse('<features>F1</features>'));
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId('body-draft')).toHaveTextContent('<features>F1</features>'),
    );
  });

  it('renders both draft and review when status=approved', async () => {
    mockedGetState.mockResolvedValue(
      stateResponse({
        status: 'approved',
        draft: { body_path: 'p', body_sha256: 'x', generated_at: 't' },
        review: { body_path: 'r', body_sha256: 'y', reviewed_at: 't', score: 90 },
        approval: { approved_at: 't2', approved_by: 'alice' },
      }),
    );
    mockedGetBody.mockImplementation(
      (_p: string, _scope: unknown, _ref: string, which: 'draft' | 'review') =>
        Promise.resolve(bodyResponse(which === 'review' ? 'REVIEW_TEXT' : 'DRAFT_TEXT')),
    );
    renderPanel();
    await waitFor(() => expect(screen.getByTestId('body-draft')).toHaveTextContent('DRAFT_TEXT'));
    expect(screen.getByTestId('body-review')).toHaveTextContent('REVIEW_TEXT');
    expect(screen.getByText(/Approved at t2 by alice/)).toBeInTheDocument();
    expect(
      screen.getByText(/\/regen-feature-expansion-with-feedback proj/),
    ).toBeInTheDocument();
  });
});
