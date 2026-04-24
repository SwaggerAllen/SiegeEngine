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
    const microFields = (alias: string) =>
      `<purpose>Owns ${alias}.</purpose>` +
      '<owned-invariants>' +
      `<invariant>${alias} is well-formed</invariant>` +
      `<invariant>${alias} is journaled</invariant>` +
      '</owned-invariants>' +
      '<primary-operations>' +
      `<operation>read ${alias}</operation>` +
      `<operation>mutate ${alias}</operation>` +
      `<operation>emit ${alias}</operation>` +
      '</primary-operations>';
    const xml =
      '<introduction>Tech-stack preamble the user wants to skip past.</introduction>' +
      '<sysarch>' +
      '<techspec>' +
      '<runtime>Python 3.11</runtime><persistence>Postgres</persistence>' +
      '<write-path>event-sourced</write-path><concurrency>async</concurrency>' +
      '<testing>pytest</testing><deploy>Docker on Fly.io</deploy>' +
      '<technologies>Python, Postgres, React</technologies>' +
      '</techspec>' +
      '<components>' +
      '<component alias="billing">' +
      '<name>Billing</name><kind>domain</kind>' +
      microFields('billing') +
      '<responsibilities><resp id="resp_abc"/></responsibilities>' +
      '</component>' +
      '<component alias="auth">' +
      '<name>Auth</name><kind>domain</kind>' +
      microFields('auth') +
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
    expect(screen.queryByText(/Python 3.11/)).not.toBeInTheDocument();
  });

  it('shows a hint when the draft has no <components> block', () => {
    render(
      <SysarchComponentsTab
        content="<sysarch><techspec><runtime>x</runtime><persistence>x</persistence><write-path>x</write-path><concurrency>x</concurrency><testing>x</testing><deploy>x</deploy><technologies>x</technologies></techspec></sysarch>"
        renderers={sysarchRenderers}
      />,
    );
    expect(screen.getByText(/missing a/)).toBeInTheDocument();
  });
});
