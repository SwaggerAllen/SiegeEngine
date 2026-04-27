import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { XmlDocument } from './XmlDocument';
import type { XmlRendererMap } from './types';
import { findChildText, textContent } from './types';

describe('XmlDocument (schema-agnostic default rendering)', () => {
  it('renders a leaf text element as a paragraph', () => {
    const { container } = render(
      <XmlDocument content="<doc><p>Hello world</p></doc>" />
    );
    expect(container.querySelector('p')?.textContent).toBe('Hello world');
  });

  it('renders a <name> child as a heading and siblings as content', () => {
    const { container } = render(
      <XmlDocument content="<section><name>Title</name><body>Body text</body></section>" />
    );
    // Top-level <section> → h2 (depth=0)
    const h2 = container.querySelector('h2');
    expect(h2?.textContent).toBe('Title');
    expect(container.textContent).toContain('Body text');
  });

  it('picks progressively smaller heading levels at deeper nesting', () => {
    const { container } = render(
      <XmlDocument
        content={
          '<root>' +
          '<name>Top</name>' +
          '<child><name>Middle</name>' +
          '<grandchild><name>Bottom</name></grandchild>' +
          '</child>' +
          '</root>'
        }
      />
    );
    expect(container.querySelector('h2')?.textContent).toBe('Top');
    expect(container.querySelector('h3')?.textContent).toBe('Middle');
    expect(container.querySelector('h4')?.textContent).toBe('Bottom');
  });

  it('shows the raw fallback when the content cannot be parsed', () => {
    render(<XmlDocument content="not xml at all" />);
    expect(screen.getByText('not xml at all')).toBeInTheDocument();
  });

  it('renders every top-level element when the document has multiple roots', () => {
    // Bootstrap tiers (expansion / requirements / sysarch) emit
    // ``<introduction>...</introduction><main-block>...</main-block>``.
    // The default renderer turned a leaf <runtime>FastAPI</runtime> into
    // its inner text, so its presence is the "did the second root render"
    // signal.
    const { container } = render(
      <XmlDocument
        content={
          '<introduction>Preamble prose.</introduction>' +
          '<sysarch>' +
          '<techspec><runtime>FastAPI</runtime></techspec>' +
          '</sysarch>'
        }
      />,
    );
    expect(container.textContent).toContain('Preamble prose.');
    expect(container.textContent).toContain('FastAPI');
  });

  it('calls the custom fallback when provided', () => {
    render(
      <XmlDocument
        content="broken"
        fallback={(raw, err) => (
          <div data-testid="fb">
            fallback: {raw} ({err.message})
          </div>
        )}
      />
    );
    expect(screen.getByTestId('fb').textContent).toContain('fallback: broken');
  });
});

describe('XmlDocument (custom renderers)', () => {
  it('dispatches to a custom renderer when the tag is in the map', () => {
    const renderers: XmlRendererMap = {
      widget: (node) => (
        <div data-testid="widget">{findChildText(node, 'label') ?? 'no-label'}</div>
      ),
      label: () => null,
    };
    render(
      <XmlDocument
        content="<widget><label>Click me</label></widget>"
        renderers={renderers}
      />
    );
    expect(screen.getByTestId('widget').textContent).toBe('Click me');
  });

  it('lets a custom renderer recurse into children via ctx.renderChildren', () => {
    const renderers: XmlRendererMap = {
      outer: (node, ctx) => (
        <div data-testid="outer">{ctx.renderChildren(node.children)}</div>
      ),
      inner: (node) => <span data-testid="inner">{textContent(node).trim()}</span>,
    };
    render(
      <XmlDocument
        content="<outer><inner>one</inner><inner>two</inner></outer>"
        renderers={renderers}
      />
    );
    const inners = screen.getAllByTestId('inner');
    expect(inners.map((el) => el.textContent)).toEqual(['one', 'two']);
  });

  it('falls back to the default renderer for tags without an override', () => {
    const renderers: XmlRendererMap = {
      claimed: () => <div data-testid="custom">claimed</div>,
    };
    const { container } = render(
      <XmlDocument
        content="<root><claimed/><unclaimed><name>Anon</name></unclaimed></root>"
        renderers={renderers}
      />
    );
    expect(screen.getByTestId('custom')).toBeInTheDocument();
    // The unclaimed element goes through the default renderer and
    // produces a heading from its <name> child.
    expect(container.querySelector('h3')?.textContent).toBe('Anon');
  });
});
