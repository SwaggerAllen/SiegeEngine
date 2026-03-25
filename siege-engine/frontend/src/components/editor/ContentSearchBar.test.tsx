import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ContentSearchBar } from './ContentSearchBar';
import { createRef } from 'react';

// jsdom doesn't implement scrollIntoView
Element.prototype.scrollIntoView = vi.fn();

// Helper: render a container with known text content alongside the search bar
function renderWithContainer(text: string) {
  const containerRef = createRef<HTMLDivElement>();
  const result = render(
    <div>
      <div ref={containerRef}>{text}</div>
      <ContentSearchBar containerRef={containerRef} />
    </div>,
  );
  return { ...result, containerRef };
}

describe('ContentSearchBar', () => {
  it('renders search icon button when closed', () => {
    renderWithContainer('Hello world');
    const button = screen.getByTitle('Search in document (Ctrl+F)');
    expect(button).toBeInTheDocument();
    // Input should not be visible
    expect(screen.queryByPlaceholderText('Find in document...')).not.toBeInTheDocument();
  });

  it('opens search input when search icon is clicked', async () => {
    const user = userEvent.setup();
    renderWithContainer('Hello world');
    await user.click(screen.getByTitle('Search in document (Ctrl+F)'));
    expect(screen.getByPlaceholderText('Find in document...')).toBeInTheDocument();
  });

  it('highlights matches when typing in the search input', async () => {
    const user = userEvent.setup();
    const { containerRef } = renderWithContainer('The fox and the fox ran');

    await user.click(screen.getByTitle('Search in document (Ctrl+F)'));
    await user.type(screen.getByPlaceholderText('Find in document...'), 'fox');

    await waitFor(() => {
      const marks = containerRef.current!.querySelectorAll('mark[data-search-highlight]');
      expect(marks.length).toBe(2);
    });
  });

  it('shows match count correctly (e.g., "1/2")', async () => {
    const user = userEvent.setup();
    renderWithContainer('apple banana apple cherry apple');

    await user.click(screen.getByTitle('Search in document (Ctrl+F)'));
    await user.type(screen.getByPlaceholderText('Find in document...'), 'apple');

    await waitFor(() => {
      expect(screen.getByText('1/3')).toBeInTheDocument();
    });
  });

  it('shows "No results" when query has no matches', async () => {
    const user = userEvent.setup();
    renderWithContainer('Hello world');

    await user.click(screen.getByTitle('Search in document (Ctrl+F)'));
    await user.type(screen.getByPlaceholderText('Find in document...'), 'zzzzz');

    await waitFor(() => {
      expect(screen.getByText('No results')).toBeInTheDocument();
    });
  });

  it('navigates to next match when next button is clicked', async () => {
    const user = userEvent.setup();
    renderWithContainer('cat dog cat bird cat');

    await user.click(screen.getByTitle('Search in document (Ctrl+F)'));
    await user.type(screen.getByPlaceholderText('Find in document...'), 'cat');

    await waitFor(() => {
      expect(screen.getByText('1/3')).toBeInTheDocument();
    });

    await user.click(screen.getByTitle('Next match (Enter)'));
    expect(screen.getByText('2/3')).toBeInTheDocument();

    await user.click(screen.getByTitle('Next match (Enter)'));
    expect(screen.getByText('3/3')).toBeInTheDocument();
  });

  it('navigates to previous match when prev button is clicked', async () => {
    const user = userEvent.setup();
    renderWithContainer('cat dog cat bird cat');

    await user.click(screen.getByTitle('Search in document (Ctrl+F)'));
    await user.type(screen.getByPlaceholderText('Find in document...'), 'cat');

    await waitFor(() => {
      expect(screen.getByText('1/3')).toBeInTheDocument();
    });

    // Go to next first, then back
    await user.click(screen.getByTitle('Next match (Enter)'));
    expect(screen.getByText('2/3')).toBeInTheDocument();

    await user.click(screen.getByTitle('Previous match (Shift+Enter)'));
    expect(screen.getByText('1/3')).toBeInTheDocument();
  });

  it('clears highlights and closes when close button is clicked', async () => {
    const user = userEvent.setup();
    const { containerRef } = renderWithContainer('hello world hello');

    await user.click(screen.getByTitle('Search in document (Ctrl+F)'));
    await user.type(screen.getByPlaceholderText('Find in document...'), 'hello');

    await waitFor(() => {
      const marks = containerRef.current!.querySelectorAll('mark[data-search-highlight]');
      expect(marks.length).toBe(2);
    });

    await user.click(screen.getByTitle('Close (Escape)'));

    // Input should be gone
    expect(screen.queryByPlaceholderText('Find in document...')).not.toBeInTheDocument();
    // Highlights should be cleared
    const marks = containerRef.current!.querySelectorAll('mark[data-search-highlight]');
    expect(marks.length).toBe(0);
  });

  it('closes the search bar when Escape key is pressed', async () => {
    const user = userEvent.setup();
    renderWithContainer('Hello world');

    await user.click(screen.getByTitle('Search in document (Ctrl+F)'));
    const input = screen.getByPlaceholderText('Find in document...');
    expect(input).toBeInTheDocument();

    await user.keyboard('{Escape}');

    expect(screen.queryByPlaceholderText('Find in document...')).not.toBeInTheDocument();
  });
});
