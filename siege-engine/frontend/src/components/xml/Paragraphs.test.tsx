import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Paragraphs } from './Paragraphs';

describe('Paragraphs', () => {
  it('renders nothing for an empty string', () => {
    const { container } = render(<Paragraphs text="" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders a single paragraph as one <p>', () => {
    render(<Paragraphs text="Solo paragraph without breaks." />);
    const ps = document.querySelectorAll('p');
    expect(ps.length).toBe(1);
    expect(ps[0].textContent).toBe('Solo paragraph without breaks.');
  });

  it('splits on blank lines into multiple <p> blocks', () => {
    render(
      <Paragraphs
        text={[
          'Runs as a Python service on FastAPI.',
          '',
          'Persists sessions to Postgres via SQLAlchemy async.',
          '',
          'Tests use pytest-asyncio with an in-memory sqlite fixture.',
        ].join('\n')}
      />,
    );
    expect(
      screen.getByText('Runs as a Python service on FastAPI.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Persists sessions to Postgres via SQLAlchemy async.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Tests use pytest-asyncio with an in-memory sqlite fixture.'),
    ).toBeInTheDocument();
    expect(document.querySelectorAll('p').length).toBe(3);
  });
});
