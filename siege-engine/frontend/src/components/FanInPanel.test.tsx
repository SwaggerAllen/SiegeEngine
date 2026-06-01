import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { FanInPanel } from './FanInPanel';
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
      <FanInPanel projectId="proj_1" compId="comp_a" ownerName="Auth" />
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
    body_path: 'fanin/comp_a/body.md',
    body_text,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FanInPanel', () => {
  it('shows the absent state with a draft hint', async () => {
    mockedGetState.mockResolvedValue(stateResponse());
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/No substrate state/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/\/draft-fanin comp_a/)).toBeInTheDocument();
  });

  it('renders the draft body when status=drafted', async () => {
    mockedGetState.mockResolvedValue(
      stateResponse({
        status: 'drafted',
        draft: { body_path: 'p', body_sha256: 'x', generated_at: 't' },
      }),
    );
    mockedGetBody.mockResolvedValue(bodyResponse('<fanin>FI</fanin>'));
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId('body-draft')).toHaveTextContent('<fanin>FI</fanin>'),
    );
  });
});
