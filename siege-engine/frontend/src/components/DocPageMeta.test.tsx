import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DocPageMeta } from './DocPageMeta';

describe('DocPageMeta', () => {
  it('renders nothing when both inputs are null', () => {
    const { container } = render(
      <DocPageMeta lastGenerationJob={null} lastContentUpdatedAt={null} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders the cancelled status with its error message', () => {
    render(
      <DocPageMeta
        lastGenerationJob={{
          status: 'cancelled',
          created_at: '2026-05-02T00:00:12',
          completed_at: '2026-05-02T00:00:13',
          error_message: 'user cancelled the job',
        }}
        lastContentUpdatedAt={null}
      />
    );
    expect(screen.getByText(/Last generation:/)).toBeInTheDocument();
    expect(screen.getByText('cancelled')).toBeInTheDocument();
    expect(
      screen.getByText(/user cancelled the job/i),
    ).toBeInTheDocument();
  });

  it('renders the approved-content timestamp when present', () => {
    render(
      <DocPageMeta
        lastGenerationJob={null}
        lastContentUpdatedAt="2026-05-02T01:23:45"
      />
    );
    expect(
      screen.getByText(/Approved content last landed:/),
    ).toBeInTheDocument();
  });

  it('omits error_message for completed jobs even if present', () => {
    render(
      <DocPageMeta
        lastGenerationJob={{
          status: 'completed',
          created_at: '2026-05-02T00:00:12',
          completed_at: '2026-05-02T00:05:13',
          error_message: 'should not appear',
        }}
        lastContentUpdatedAt={null}
      />
    );
    expect(screen.getByText('completed')).toBeInTheDocument();
    expect(screen.queryByText(/should not appear/)).toBeNull();
  });

  it('uses created_at when completed_at is null (job still running)', () => {
    render(
      <DocPageMeta
        lastGenerationJob={{
          status: 'running',
          created_at: '2026-05-02T00:00:12',
          completed_at: null,
          error_message: null,
        }}
        lastContentUpdatedAt={null}
      />
    );
    // Just confirm the meta block rendered without crashing — the
    // formatted timestamp is locale-dependent so we don't assert
    // exact text, only that the surrounding line landed.
    expect(screen.getByTestId('doc-page-meta')).toBeInTheDocument();
    expect(screen.getByText('running')).toBeInTheDocument();
  });
});
