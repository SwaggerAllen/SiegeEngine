import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReferenceDetail } from '../api/references';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ReferencePanel } from './ReferencePanel';

const apiStub: {
  list: ReturnType<typeof vi.fn>;
  getDetail: ReturnType<typeof vi.fn>;
} = {
  list: vi.fn(),
  getDetail: vi.fn(),
};

vi.mock('../api/references', async () => {
  const actual = await vi.importActual<typeof import('../api/references')>(
    '../api/references',
  );
  return {
    ...actual,
    makeReferencesApi: vi.fn(() => apiStub),
  };
});

function renderPanel(refId: string | null = 'ref_AAAAAAAA') {
  return render(
    <TestQueryWrapper>
      <ReferencePanel projectId="proj_1" refId={refId} />
    </TestQueryWrapper>,
  );
}

function detail(overrides: Partial<ReferenceDetail> = {}): ReferenceDetail {
  return {
    node: {
      id: 'ref_AAAAAAAA',
      name: 'Runbook',
      content: '',
      updated_at: '2026-04-16T00:00:00',
    },
    outgoing_edges: [],
    incoming_edges: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ReferencePanel', () => {
  it('shows an empty placeholder when no ref is selected', () => {
    renderPanel(null);
    expect(screen.getByText(/Select a reference/i)).toBeInTheDocument();
  });

  it('renders approved content via the XML renderer', async () => {
    apiStub.getDetail.mockResolvedValue(
      detail({
        node: {
          id: 'ref_AAAAAAAA',
          name: 'Runbook',
          content:
            '<reference><title>Approved</title><body>Body.</body></reference>',
          updated_at: '2026-04-16T00:00:00',
        },
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/Approved/)).toBeInTheDocument(),
    );
  });

  it('lists outgoing reference edges', async () => {
    apiStub.getDetail.mockResolvedValue(
      detail({
        outgoing_edges: [
          {
            edge_id: 'edge_1',
            source_id: 'ref_AAAAAAAA',
            target_id: 'comp_BILLING1',
          },
        ],
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/comp_BILLING1/)).toBeInTheDocument(),
    );
  });

  it('points users at the /create_ref skill for authoring', async () => {
    apiStub.getDetail.mockResolvedValue(detail());
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/\/create_ref/)).toBeInTheDocument(),
    );
  });
});
