import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SysarchComponentsTab } from './SysarchComponentsTab';
import { sysarchRenderers } from './xml';

describe('SysarchComponentsTab', () => {
  it('renders a hint when content is empty', () => {
    render(
      <SysarchComponentsTab content="" renderers={sysarchRenderers} />,
    );
    expect(screen.getByText(/No content yet/)).toBeInTheDocument();
  });

  it('extracts and renders the components subtree from a full sysarch draft', () => {
    const xml =
      '<introduction>Tech-stack preamble the user wants to skip past.</introduction>' +
      '<sysarch>' +
      '<techspec>Python + React.</techspec>' +
      '<components>' +
      '<component alias="billing">' +
      '<name>Billing</name>' +
      '<kind>domain</kind>' +
      '<role>Owns invoice lifecycle.</role>' +
      '<api-intent>billing.charge(account_id).</api-intent>' +
      '<responsibilities><resp id="resp_abc"/></responsibilities>' +
      '</component>' +
      '<component alias="auth">' +
      '<name>Auth</name>' +
      '<kind>domain</kind>' +
      '<role>Identifies callers.</role>' +
      '<api-intent>auth.login().</api-intent>' +
      '<responsibilities><resp id="resp_def"/></responsibilities>' +
      '</component>' +
      '</components>' +
      '<policies></policies>' +
      '</sysarch>';
    render(
      <SysarchComponentsTab content={xml} renderers={sysarchRenderers} />,
    );
    expect(screen.getByText('Billing')).toBeInTheDocument();
    expect(screen.getByText('Auth')).toBeInTheDocument();
    // Introduction + techspec must not leak.
    expect(screen.queryByText(/Tech-stack preamble/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Python \+ React/)).not.toBeInTheDocument();
  });

  it('shows a hint when the draft has no <components> block', () => {
    render(
      <SysarchComponentsTab
        content="<sysarch><techspec>only techspec</techspec></sysarch>"
        renderers={sysarchRenderers}
      />,
    );
    expect(screen.getByText(/missing a/)).toBeInTheDocument();
  });
});
