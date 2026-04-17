import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { XmlDocument } from './XmlDocument';
import { featureRenderers } from './featureRenderers';

function renderFeatures(xml: string) {
  return render(<XmlDocument content={xml} renderers={featureRenderers} />);
}

describe('featureRenderers', () => {
  it('renders a single feature as a card with name and intent', () => {
    renderFeatures(
      '<features>' +
        '<feature><name>Billing</name><intent>Users pay for plans.</intent></feature>' +
        '</features>'
    );
    expect(screen.getByText('Billing')).toBeInTheDocument();
    expect(screen.getByText('Users pay for plans.')).toBeInTheDocument();
  });

  it('shows the inferred badge only when <implicit/> is present', () => {
    renderFeatures(
      '<features>' +
        '<feature><name>Login</name><intent>Sign in.</intent></feature>' +
        '<feature><name>Password Reset</name><intent>Forgot password flow.</intent><implicit/></feature>' +
        '</features>'
    );
    const badges = screen.getAllByText(/inferred/i);
    expect(badges).toHaveLength(1);
    // The badge lives in the summary row next to the implicit feature's name.
    const resetSummary = screen.getByText('Password Reset').closest('summary');
    expect(resetSummary?.textContent).toMatch(/inferred/);
  });

  it('renders a group with a heading, count, and nested feature cards', () => {
    renderFeatures(
      '<features>' +
        '<group>' +
        '<name>User Management</name>' +
        '<feature><name>Login</name><intent>Sign in.</intent></feature>' +
        '<feature><name>Signup</name><intent>Create an account.</intent></feature>' +
        '</group>' +
        '</features>'
    );
    const groupHeading = screen.getByRole('heading', { name: /User Management/ });
    expect(groupHeading).toBeInTheDocument();
    // Count annotation inside the same heading.
    expect(groupHeading.textContent).toContain('(2)');
    expect(screen.getByText('Login')).toBeInTheDocument();
    expect(screen.getByText('Signup')).toBeInTheDocument();
  });

  it('renders mixed grouped and ungrouped features', () => {
    renderFeatures(
      '<features>' +
        '<group>' +
        '<name>Core</name>' +
        '<feature><name>Login</name><intent>Sign in.</intent></feature>' +
        '</group>' +
        '<feature><name>Search</name><intent>Search everything.</intent></feature>' +
        '</features>'
    );
    expect(screen.getByRole('heading', { name: /Core/ })).toBeInTheDocument();
    expect(screen.getByText('Login')).toBeInTheDocument();
    expect(screen.getByText('Search')).toBeInTheDocument();
    expect(screen.getByText('Search everything.')).toBeInTheDocument();
  });

  it('does not leak raw tag text when a stray <name> appears at the root', () => {
    // Shouldn't normally happen — validator catches it — but if it
    // does, the <name>/<intent>/<implicit> renderers return null so
    // the tag text is not rendered as a string.
    const { container } = renderFeatures('<features><name>StrayName</name></features>');
    expect(container.textContent).not.toContain('StrayName');
  });

  it('falls back to the raw string when parsing fails entirely', () => {
    renderFeatures('this is definitely not xml');
    expect(screen.getByText('this is definitely not xml')).toBeInTheDocument();
  });
});
