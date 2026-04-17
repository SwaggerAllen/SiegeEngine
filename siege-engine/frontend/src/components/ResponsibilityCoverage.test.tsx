import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { StructureResponse } from '../api/structure';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ResponsibilityCoverage } from './ResponsibilityCoverage';

vi.mock('../api/structure', async () => {
  const actual = await vi.importActual<typeof import('../api/structure')>('../api/structure');
  return {
    ...actual,
    getProjectStructure: vi.fn(),
  };
});

import * as structureApi from '../api/structure';

const mocked = structureApi.getProjectStructure as unknown as ReturnType<typeof vi.fn>;

function fixture(overrides: Partial<StructureResponse> = {}): StructureResponse {
  return {
    offset: 0,
    nodes: [],
    edges: [],
    ...overrides,
  };
}

function n(
  id: string,
  tier: string,
  parent_id: string | null,
  extras: Partial<StructureResponse['nodes'][number]> = {},
): StructureResponse['nodes'][number] {
  return {
    id,
    tier,
    kind: 'domain',
    parent_id,
    name: id,
    display_order: 0,
    content: '',
    has_content: false,
    has_pending_draft: false,
    generation_running: false,
    has_error: false,
    has_cancelled_latest_job: false,
    techspec: '',
    pubapi: '',
    ...extras,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ResponsibilityCoverage', () => {
  it('renders received resps from decomposition edges', async () => {
    mocked.mockResolvedValue(
      fixture({
        nodes: [
          n('comp_C', 'comp', null),
          n('resp_TOP1', 'resp', null, {
            name: 'Authenticate users',
            content: 'Verify creds.',
            has_content: true,
          }),
          n('resp_TOP2', 'resp', null, {
            name: 'Manage sessions',
            content: 'Maintain sessions.',
            has_content: true,
          }),
        ],
        edges: [
          { id: 'e1', edge_type: 'decomposition', source_id: 'resp_TOP1', target_id: 'comp_C' },
          { id: 'e2', edge_type: 'decomposition', source_id: 'resp_TOP2', target_id: 'comp_C' },
        ],
      }),
    );

    render(
      <TestQueryWrapper>
        <ResponsibilityCoverage projectId="p1" compId="comp_C" />
      </TestQueryWrapper>,
    );

    await waitFor(() =>
      expect(screen.getByText('Authenticate users')).toBeInTheDocument(),
    );
    expect(screen.getByText('Manage sessions')).toBeInTheDocument();
    expect(screen.getByText('Verify creds.')).toBeInTheDocument();
    expect(screen.getByText('Received')).toBeInTheDocument();
  });

  it('renders computed subresps as children of the comp', async () => {
    mocked.mockResolvedValue(
      fixture({
        nodes: [
          n('comp_C', 'comp', null),
          n('resp_S1', 'resp', 'comp_C', {
            name: 'Password hashing',
            content: 'Bcrypt.',
            has_content: true,
          }),
          n('resp_S2', 'resp', 'comp_C', {
            name: 'Session tokens',
            content: 'Opaque UUID4.',
            has_content: true,
            display_order: 1,
          }),
        ],
      }),
    );

    render(
      <TestQueryWrapper>
        <ResponsibilityCoverage projectId="p1" compId="comp_C" />
      </TestQueryWrapper>,
    );

    await waitFor(() =>
      expect(screen.getByText('Password hashing')).toBeInTheDocument(),
    );
    expect(screen.getByText('Session tokens')).toBeInTheDocument();
    expect(screen.getByText('Bcrypt.')).toBeInTheDocument();
  });

  it('shows empty hints when neither list has entries', async () => {
    mocked.mockResolvedValue(
      fixture({
        nodes: [n('comp_C', 'comp', null)],
      }),
    );

    render(
      <TestQueryWrapper>
        <ResponsibilityCoverage projectId="p1" compId="comp_C" />
      </TestQueryWrapper>,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/No top-level responsibilities assigned/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/No subresponsibilities yet/)).toBeInTheDocument();
  });

  it('ignores resps assigned to other comps', async () => {
    mocked.mockResolvedValue(
      fixture({
        nodes: [
          n('comp_C', 'comp', null),
          n('comp_OTHER', 'comp', null),
          n('resp_OtherMine', 'resp', null, { name: 'OtherResp' }),
          n('resp_Sub_other', 'resp', 'comp_OTHER', { name: 'OtherSub' }),
        ],
        edges: [
          {
            id: 'e1',
            edge_type: 'decomposition',
            source_id: 'resp_OtherMine',
            target_id: 'comp_OTHER',
          },
        ],
      }),
    );

    render(
      <TestQueryWrapper>
        <ResponsibilityCoverage projectId="p1" compId="comp_C" />
      </TestQueryWrapper>,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/No top-level responsibilities assigned/),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText('OtherResp')).not.toBeInTheDocument();
    expect(screen.queryByText('OtherSub')).not.toBeInTheDocument();
  });
});
