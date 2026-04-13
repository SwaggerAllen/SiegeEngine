import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { PolicyList } from './PolicyList';
import type { PolicyListResponse } from '../api/sysarch';

vi.mock('../api/sysarch', () => ({
  getPolicies: vi.fn(),
}));

import * as sysarchApi from '../api/sysarch';

const mockedGet = sysarchApi.getPolicies as unknown as ReturnType<typeof vi.fn>;

function renderList(mintPending: boolean = false) {
  return render(
    <TestQueryWrapper>
      <PolicyList projectId="proj_1" mintPending={mintPending} />
    </TestQueryWrapper>
  );
}

function makeResponse(
  policies: Array<{ id: string; name: string; content: string; display_order: number }> = []
): PolicyListResponse {
  return {
    policies: policies.map((p) => ({ ...p, updated_at: '2026-04-13T00:00:00' })),
  };
}

const TELEMETRY_BLOB = (
  '<policy>' +
  '<name>Telemetry</name>' +
  '<trigger>any LLM call</trigger>' +
  '<required>resp_audit001</required>' +
  '<rationale>Record tokens and model for audit.</rationale>' +
  '</policy>'
);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('PolicyList', () => {
  it('shows loading state initially', async () => {
    mockedGet.mockImplementation(() => new Promise(() => {}));
    renderList();
    await waitFor(() =>
      expect(screen.getByText(/Loading policies/i)).toBeInTheDocument()
    );
  });

  it('shows empty state when no policies', async () => {
    mockedGet.mockResolvedValue(makeResponse([]));
    renderList(false);
    await waitFor(() =>
      expect(screen.getByText(/No policies yet/i)).toBeInTheDocument()
    );
  });

  it('parses policy blob and renders fields', async () => {
    mockedGet.mockResolvedValue(
      makeResponse([
        {
          id: 'policy_tele01',
          name: 'Telemetry',
          content: TELEMETRY_BLOB,
          display_order: 0,
        },
      ])
    );
    renderList(false);

    await waitFor(() => expect(screen.getByText('Telemetry')).toBeInTheDocument());
    expect(screen.getByText(/on any LLM call/i)).toBeInTheDocument();
    expect(screen.getByText(/requires/)).toBeInTheDocument();
    expect(screen.getByText('resp_audit001')).toBeInTheDocument();
    expect(screen.getByText(/Record tokens and model for audit/i)).toBeInTheDocument();
  });

  it('falls back to raw content on malformed blob', async () => {
    mockedGet.mockResolvedValue(
      makeResponse([
        {
          id: 'policy_bad001',
          name: 'Malformed',
          content: 'not xml',
          display_order: 0,
        },
      ])
    );
    renderList(false);

    await waitFor(() => expect(screen.getByText('Malformed')).toBeInTheDocument());
    expect(screen.getByText('not xml')).toBeInTheDocument();
  });
});
