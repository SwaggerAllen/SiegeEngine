import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { XmlBlock } from './XmlBlock';

describe('XmlBlock', () => {
  it('renders valid XML through the viewer (not the raw fallback)', () => {
    const raw =
      '<features><feature><name>Billing</name><intent>Pay plans.</intent></feature></features>';
    render(<XmlBlock content={raw} />);
    // The viewer splits tags + text into distinct nodes; the fact
    // that these individual pieces show up (rather than a single
    // concatenated raw string) tells us the library parsed and
    // rendered the XML.
    expect(screen.getByText('Billing')).toBeInTheDocument();
    expect(screen.getByText('Pay plans.')).toBeInTheDocument();
    // "features" and "feature" tag names appear as text in the
    // syntax-highlighted tag markers.
    expect(screen.getAllByText('features').length).toBeGreaterThan(0);
    expect(screen.getAllByText('feature').length).toBeGreaterThan(0);
  });

  it('renders multi-feature structure with all names visible', () => {
    const raw =
      '<features>' +
      '<feature><name>Alpha</name><intent>First.</intent></feature>' +
      '<feature><name>Beta</name><intent>Second.</intent></feature>' +
      '</features>';
    render(<XmlBlock content={raw} />);
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('Beta')).toBeInTheDocument();
    expect(screen.getByText('First.')).toBeInTheDocument();
    expect(screen.getByText('Second.')).toBeInTheDocument();
  });

  it('falls back to the raw text when the string is not valid XML', () => {
    const raw = 'This is not XML at all, just free-form prose.';
    render(<XmlBlock content={raw} />);
    // The invalidXml fallback renders the raw string in a <pre>.
    expect(screen.getByText(raw)).toBeInTheDocument();
  });

  it('mounts inside the styled container wrapper', () => {
    render(<XmlBlock content="<a><b>x</b></a>" />);
    expect(screen.getByTestId('xml-block')).toBeInTheDocument();
  });
});
