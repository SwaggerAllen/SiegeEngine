import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { SysarchPanel } from './SysarchPanel';
import type { SysarchResponse } from '../api/sysarch';

vi.mock('../api/sysarch', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../api/sysarch')>();
  return {
    ...actual,
    getSysarch: vi.fn(),
    postFeedback: vi.fn(),
    approveDraft: vi.fn(),
    cancelGeneration: vi.fn(),
    resetSysarch: vi.fn(),
    getComponents: vi.fn(),
    getPolicies: vi.fn(),
  };
});

import * as sysarchApi from '../api/sysarch';

const mockedGet = sysarchApi.getSysarch as unknown as ReturnType<typeof vi.fn>;

function renderPanel() {
  return render(
    <TestQueryWrapper>
      <SysarchPanel projectId="proj_1" />
    </TestQueryWrapper>
  );
}

function makeResponse(overrides: Partial<SysarchResponse> = {}): SysarchResponse {
  return {
    node: {
      id: 'sysarch_1',
      name: 'System Architecture',
      content: '',
      updated_at: '2026-04-13T00:00:00',
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
    last_generation_job: null,
    last_content_updated_at: null,
    is_stale: false,
    staleness_reasons: [],
    ...overrides,
  };
}

const _MICRO_FIELDS = (alias: string) =>
  `<purpose>Owns ${alias}.</purpose>` +
  '<owned-invariants>' +
  `<invariant>${alias} holds its state</invariant>` +
  `<invariant>${alias} state is journaled</invariant>` +
  '</owned-invariants>' +
  '<primary-operations>' +
  `<operation>read ${alias} state</operation>` +
  `<operation>mutate ${alias} state</operation>` +
  `<operation>emit ${alias} events</operation>` +
  '</primary-operations>';

const _TECHSPEC =
  '<techspec>' +
  '<runtime>Python 3.11.</runtime>' +
  '<persistence>Postgres.</persistence>' +
  '<write-path>Event-sourced reducer.</write-path>' +
  '<concurrency>Async loop.</concurrency>' +
  '<testing>pytest.</testing>' +
  '<deploy>Docker on Fly.io.</deploy>' +
  '<technologies>Python, Postgres, React.</technologies>' +
  '</techspec>';

const SAMPLE_DRAFT =
  '<sysarch>' +
  _TECHSPEC +
  '<components>' +
  '<component alias="auth">' +
  '<name>Authentication</name><kind>domain</kind>' +
  _MICRO_FIELDS('auth') +
  '<responsibilities><resp id="resp_abc12345"/></responsibilities>' +
  '</component>' +
  '<component alias="foundation">' +
  '<name>Foundation</name><kind>domain</kind>' +
  _MICRO_FIELDS('foundation') +
  '<responsibilities><resp id="resp_def67890"/></responsibilities>' +
  '<foundation/>' +
  '</component>' +
  '</components>' +
  '<policies></policies>' +
  '<dependencies><dep from="auth" to="foundation"/></dependencies>' +
  '<domain-parent></domain-parent>' +
  '</sysarch>';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SysarchPanel', () => {
  it('shows a spinner while generating with no pending draft', async () => {
    mockedGet.mockResolvedValue(makeResponse({ generation_status: 'running' }));
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/Generating system architecture/i)).toBeInTheDocument()
    );
  });

  // TODO Phase 3 reinstate test once dashboard is read-only:
  //   - invokes approveDraft when Approve is clicked
  //   - invokes feedback (empty) when Reject & Regenerate is clicked without feedback text
  //   - sends typed feedback when Reject & Regenerate is clicked with feedback text
  //   - reset button requires two-click confirm
  // The merged Approve/Reject/Reset action surface is gone; equivalents
  // are CC skills, not click handlers.
  it('renders pending draft body with the Open-in-CC fallback', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content: SAMPLE_DRAFT,
          created_at: '2026-04-13T00:00:00',
        },
      })
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText('Authentication')).toBeInTheDocument());
    expect(screen.getByText('Foundation')).toBeInTheDocument();
    expect(
      screen.getByTitle(/owns the root folder territory/i)
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Approve/i })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject & Regenerate' })).toBeNull();
    expect(
      screen.getAllByRole('button', { name: /Open in Claude Code/i }).length,
    ).toBeGreaterThan(0);
  });

  it('renders approved content as read-only with Open-in-CC reset', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        node: {
          id: 'sysarch_1',
          name: 'System Architecture',
          content: SAMPLE_DRAFT,
          updated_at: '2026-04-13T00:00:00',
        },
      })
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText('Authentication')).toBeInTheDocument());
    expect(screen.getByText(/Approved · read-only/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Reset & Regenerate/i })).toBeNull();
    // The reset affordance remains as an Open-in-CC fallback.
    expect(
      screen.getAllByRole('button', { name: /Open in Claude Code/i }).length,
    ).toBeGreaterThan(0);
  });

  it('shows an error banner with Open-in-CC when generation failed and no content', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        generation_status: 'failed',
        last_error: 'parse error',
      })
    );
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText(/Generation failed/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/parse error/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Retry$/i })).toBeNull();
    expect(
      screen.getAllByRole('button', { name: /Open in Claude Code/i }).length,
    ).toBeGreaterThan(0);
  });
});
