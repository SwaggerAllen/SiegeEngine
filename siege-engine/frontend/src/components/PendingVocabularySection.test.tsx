import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { parsePendingVocabulary } from '../lib/parsePendingVocabulary';
import { PendingVocabularySection } from './PendingVocabularySection';

vi.mock('../api/expansion', async () => {
  const actual =
    await vi.importActual<typeof import('../api/expansion')>('../api/expansion');
  return { ...actual, getExpansion: vi.fn() };
});

import * as expansionApi from '../api/expansion';

const mocked = expansionApi.getExpansion as unknown as ReturnType<typeof vi.fn>;

const NODE_STUB = {
  id: 'expansion_A',
  name: 'Feature Expansion',
  content: '',
  tier: 'expansion',
};

function pending(content: string) {
  return {
    node: NODE_STUB,
    pending_draft: { id: 'draft_1', content, created_at: 'now', attempt_index: 1 },
    generation_status: 'idle',
    last_error: null,
    latest_telemetry: null,
    review_text: '',
    review_status: 'idle',
    review_last_error: null,
    review_started_at: null,
    review_current_attempt: 0,
    review_max_attempts: 0,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('parsePendingVocabulary', () => {
  it('returns empty when xml is null', () => {
    expect(parsePendingVocabulary(null)).toEqual([]);
  });

  it('returns empty when there is no vocabulary block', () => {
    expect(parsePendingVocabulary('<features></features>')).toEqual([]);
  });

  it('parses project + feature-scoped terms with disambiguation', () => {
    const xml =
      '<features></features>' +
      '<vocabulary>' +
      '<term name="session" scope="project">' +
      '<vocab-entry>' +
      '<definition>An authenticated interaction context.</definition>' +
      '<disambiguation>Not an HTTP session.</disambiguation>' +
      '</vocab-entry>' +
      '</term>' +
      '<term name="tranche" scope="feature" feature-name="Billing">' +
      '<vocab-entry>' +
      '<definition>A time-bounded batch of invoices.</definition>' +
      '</vocab-entry>' +
      '</term>' +
      '</vocabulary>';
    const entries = parsePendingVocabulary(xml);
    expect(entries).toHaveLength(2);
    expect(entries[0]).toMatchObject({
      name: 'session',
      scope: 'project',
      featureName: null,
      disambiguation: 'Not an HTTP session.',
    });
    expect(entries[1]).toMatchObject({
      name: 'tranche',
      scope: 'feature',
      featureName: 'Billing',
      disambiguation: null,
    });
  });
});

describe('PendingVocabularySection', () => {
  it('renders nothing when there is no pending draft', async () => {
    mocked.mockResolvedValue({
      node: NODE_STUB,
      pending_draft: null,
      generation_status: 'idle',
      last_error: null,
      latest_telemetry: null,
      review_text: '',
      review_status: 'idle',
      review_last_error: null,
      review_started_at: null,
      review_current_attempt: 0,
      review_max_attempts: 0,
    });
    const { container } = render(
      <TestQueryWrapper>
        <PendingVocabularySection projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() => expect(mocked).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('renders pending terms with the amber banner when the draft has vocabulary', async () => {
    mocked.mockResolvedValue(
      pending(
        '<features></features>' +
          '<vocabulary>' +
          '<term name="session" scope="project">' +
          '<vocab-entry><definition>An auth ctx.</definition></vocab-entry>' +
          '</term>' +
          '</vocabulary>',
      ),
    );
    render(
      <TestQueryWrapper>
        <PendingVocabularySection projectId="p1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Pending vocabulary/)).toBeInTheDocument(),
    );
    expect(screen.getByText('session')).toBeInTheDocument();
    expect(screen.getByText('An auth ctx.')).toBeInTheDocument();
    expect(screen.getByText(/not yet minted/i)).toBeInTheDocument();
  });
});
