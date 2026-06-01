import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ImplPanel } from './ImplPanel';
import type { BodyResponse, ScopeStateResponse } from '../api/siege';

vi.mock('../api/siege', () => ({
  getScopeState: vi.fn(),
  getBody: vi.fn(),
}));

import * as siegeApi from '../api/siege';

const mockedGetState = siegeApi.getScopeState as unknown as ReturnType<typeof vi.fn>;
const mockedGetBody = siegeApi.getBody as unknown as ReturnType<typeof vi.fn>;

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
    body_path: 'impl/comp_a/body.md',
    body_text,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ImplPanel', () => {
  it('renders top-level scope and includes the comp id in the hint', async () => {
    mockedGetState.mockResolvedValue(stateResponse());
    render(
      <TestQueryWrapper>
        <ImplPanel kind="top-level" projectId="proj_1" compId="comp_a" ownerName="Auth" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/No substrate state/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/\/draft-impl comp_a/)).toBeInTheDocument();
  });

  it('renders sub scope with the sub id in the hint and shows draft body', async () => {
    mockedGetState.mockResolvedValue(
      stateResponse({
        status: 'drafted',
        draft: { body_path: 'p', body_sha256: 'x', generated_at: 't' },
      }),
    );
    mockedGetBody.mockResolvedValue(bodyResponse('<impl>OK</impl>'));
    render(
      <TestQueryWrapper>
        <ImplPanel
          kind="sub"
          projectId="proj_1"
          parentCompId="comp_a"
          subId="sub_b"
          ownerName="TokenStore"
        />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByTestId('body-draft')).toHaveTextContent('<impl>OK</impl>'),
    );
    expect(screen.getByText(/\/review-impl sub_b/)).toBeInTheDocument();
  });
});
