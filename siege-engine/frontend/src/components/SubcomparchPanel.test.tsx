import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { SubcomparchPanel } from './SubcomparchPanel';
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
      <SubcomparchPanel
        projectId="proj_1"
        parentCompId="comp_a"
        subId="sub_b"
        subName="TokenStore"
      />
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
    body_path: 'subcomparch/comp_a/subs/sub_b/body.md',
    body_text,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SubcomparchPanel', () => {
  it('shows the absent state with a draft hint targeting the sub id', async () => {
    mockedGetState.mockResolvedValue(stateResponse());
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/No substrate state/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/\/draft-subcomparch sub_b/)).toBeInTheDocument();
  });

  it('renders the draft body when status=drafted', async () => {
    mockedGetState.mockResolvedValue(
      stateResponse({
        status: 'drafted',
        draft: { body_path: 'p', body_sha256: 'x', generated_at: 't' },
      }),
    );
    mockedGetBody.mockResolvedValue(bodyResponse('<subcomparch>SC</subcomparch>'));
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId('body-draft')).toHaveTextContent('<subcomparch>SC</subcomparch>'),
    );
  });
});
