import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { StructuredDraftDiffView } from './StructuredDraftDiffView';

describe('StructuredDraftDiffView', () => {
  it('shows per-section status badges on sysarch drafts', () => {
    const before =
      '<sysarch>' +
      '<components>' +
      '<component alias="billing"><name>Billing</name><role>v1</role></component>' +
      '<component alias="auth"><name>Auth</name><role>v1</role></component>' +
      '</components>' +
      '</sysarch>';
    const after =
      '<sysarch>' +
      '<components>' +
      '<component alias="billing"><name>Billing</name><role>v2 revised</role></component>' +
      '<component alias="reporting"><name>Reporting</name><role>new</role></component>' +
      '</components>' +
      '</sysarch>';

    render(<StructuredDraftDiffView before={before} after={after} kind="sysarch" />);

    // Summary counts — 1 changed (Billing), 1 added (Reporting), 1 removed (Auth).
    expect(screen.getByText(/1 changed/)).toBeInTheDocument();
    expect(screen.getByText(/1 added/)).toBeInTheDocument();
    expect(screen.getByText(/1 removed/)).toBeInTheDocument();

    // All three component labels visible.
    expect(screen.getByText('Billing')).toBeInTheDocument();
    expect(screen.getByText('Reporting')).toBeInTheDocument();
    expect(screen.getByText('Auth')).toBeInTheDocument();
  });

  it('lists per-feature sections for expansion drafts', () => {
    const before =
      '<features>' +
      '<feature><name>Login</name><intent>v1</intent></feature>' +
      '</features>';
    const after =
      '<features>' +
      '<feature><name>Login</name><intent>v2</intent></feature>' +
      '<feature><name>Billing</name><intent>new</intent></feature>' +
      '</features>';
    render(
      <StructuredDraftDiffView before={before} after={after} kind="expansion" />,
    );
    expect(screen.getByText('Login')).toBeInTheDocument();
    expect(screen.getByText('Billing')).toBeInTheDocument();
  });

  it('shows a no-changes hint when all sections are identical', () => {
    const xml =
      '<sysarch>' +
      '<components>' +
      '<component alias="billing"><name>Billing</name><role>v1</role></component>' +
      '</components>' +
      '</sysarch>';
    render(<StructuredDraftDiffView before={xml} after={xml} kind="sysarch" />);
    expect(screen.getByText(/No per-section changes/i)).toBeInTheDocument();
  });

  it('falls back to flat diff when the content cannot be parsed as sections', () => {
    // A tier that has no matching container falls through to the
    // raw DraftDiffView. Confirm the StructuredDraftDiffView shell
    // (summary badges, accordions) is absent — DraftDiffView
    // doesn't render any of those.
    const before = 'line one\nline two\nline three';
    const after = 'line one\nDIFFERENT line two\nline three';
    render(
      <StructuredDraftDiffView before={before} after={after} kind="sysarch" />,
    );
    expect(screen.queryByText(/changed$/)).not.toBeInTheDocument();
    // DraftDiffView's layout toggle survives the fallback.
    expect(
      screen.getByRole('button', { name: /Side-by-side/i }),
    ).toBeInTheDocument();
  });

  it('expands changed sections and collapses unchanged ones by default', async () => {
    const before =
      '<sysarch>' +
      '<components>' +
      '<component alias="billing"><name>Billing</name><role>v1</role></component>' +
      '<component alias="auth"><name>Auth</name><role>same</role></component>' +
      '</components>' +
      '</sysarch>';
    const after =
      '<sysarch>' +
      '<components>' +
      '<component alias="billing"><name>Billing</name><role>v2</role></component>' +
      '<component alias="auth"><name>Auth</name><role>same</role></component>' +
      '</components>' +
      '</sysarch>';
    render(<StructuredDraftDiffView before={before} after={after} kind="sysarch" />);

    // Billing accordion should be open (changed → default expanded).
    const billingButton = screen.getByRole('button', { name: /Billing/i });
    expect(billingButton).toHaveAttribute('aria-expanded', 'true');

    // Auth accordion should be collapsed (unchanged).
    const authButton = screen.getByRole('button', { name: /Auth/i });
    expect(authButton).toHaveAttribute('aria-expanded', 'false');

    // Clicking Auth opens it.
    const user = userEvent.setup();
    await user.click(authButton);
    expect(authButton).toHaveAttribute('aria-expanded', 'true');
  });
});
