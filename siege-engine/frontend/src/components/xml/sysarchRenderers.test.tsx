import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { XmlDocument } from './XmlDocument';
import { makeSysarchRenderers } from './sysarchRenderers';

/**
 * The orphan-resp warning lives on the ``components`` section
 * renderer: it scans every ``<component kind="domain">`` in the
 * draft, collects assigned resp IDs, and flags any known resp
 * (from the caller-supplied ``respNames`` map) that the draft
 * failed to assign. Single linear pass over the tree.
 */
describe('sysarchRenderers orphan-resp warning', () => {
  const COMPONENT_XML = (resp: string) =>
    `<component alias="${resp}">` +
    `<name>${resp}</name>` +
    '<kind>domain</kind>' +
    '<purpose>Owns x.</purpose>' +
    '<owned-invariants>' +
    '<invariant>x holds</invariant>' +
    '<invariant>y holds</invariant>' +
    '</owned-invariants>' +
    '<primary-operations>' +
    '<operation>do x</operation>' +
    '<operation>do y</operation>' +
    '<operation>do z</operation>' +
    '</primary-operations>' +
    `<responsibilities><resp id="${resp}"/></responsibilities>` +
    '</component>';

  const wrapInSysarch = (componentsXml: string) =>
    '<sysarch>' +
    '<techspec>' +
    '<runtime>x</runtime><persistence>x</persistence>' +
    '<write-path>x</write-path><concurrency>x</concurrency>' +
    '<testing>x</testing><deploy>x</deploy>' +
    '<technologies>x</technologies>' +
    '</techspec>' +
    `<components>${componentsXml}</components>` +
    '<policies></policies>' +
    '<dependencies></dependencies>' +
    '<domain-parent></domain-parent>' +
    '</sysarch>';

  it('flags a known resp that no component claims', () => {
    const respNames = {
      resp_auth: 'Authentication',
      resp_billing: 'Billing',
      resp_orphaned: 'Missing Resp',
    };
    const renderers = makeSysarchRenderers(respNames);
    const xml = wrapInSysarch(
      COMPONENT_XML('resp_auth') + COMPONENT_XML('resp_billing'),
    );
    render(<XmlDocument content={xml} renderers={renderers} />);
    expect(
      screen.getByText(/1 responsibility not assigned/),
    ).toBeInTheDocument();
    expect(screen.getByText('Missing Resp')).toBeInTheDocument();
    expect(screen.getByText('(resp_orphaned)')).toBeInTheDocument();
  });

  it('pluralizes the warning when multiple resps are missing', () => {
    const respNames = {
      resp_a: 'Alpha',
      resp_b: 'Beta',
      resp_c: 'Gamma',
    };
    const renderers = makeSysarchRenderers(respNames);
    const xml = wrapInSysarch(COMPONENT_XML('resp_a'));
    render(<XmlDocument content={xml} renderers={renderers} />);
    expect(
      screen.getByText(/2 responsibilities not assigned/),
    ).toBeInTheDocument();
    expect(screen.getByText('Beta')).toBeInTheDocument();
    expect(screen.getByText('Gamma')).toBeInTheDocument();
  });

  it('suppresses the warning when every known resp is assigned', () => {
    const respNames = {
      resp_auth: 'Authentication',
      resp_billing: 'Billing',
    };
    const renderers = makeSysarchRenderers(respNames);
    const xml = wrapInSysarch(
      COMPONENT_XML('resp_auth') + COMPONENT_XML('resp_billing'),
    );
    render(<XmlDocument content={xml} renderers={renderers} />);
    expect(
      screen.queryByText(/not assigned to any component/),
    ).not.toBeInTheDocument();
  });

  it('skips the warning when respNames is empty', () => {
    // Default module-level export use case: caller has no resp
    // roster to diff against, so the check is a no-op even when
    // the draft is incomplete. Prevents the warning from firing
    // in contexts (e.g. raw-text previews) that can't populate
    // the lookup map.
    const renderers = makeSysarchRenderers({});
    const xml = wrapInSysarch(COMPONENT_XML('resp_auth'));
    render(<XmlDocument content={xml} renderers={renderers} />);
    expect(
      screen.queryByText(/not assigned to any component/),
    ).not.toBeInTheDocument();
  });

  it('does not count presentational-component assignments', () => {
    // Presentational components mirror resps from their domain
    // parent — they don't primary-own them. The orphan check only
    // counts domain-component assignments, so a resp that only
    // appears in a presentational is still an orphan.
    const respNames = {
      resp_billing: 'Billing',
    };
    const renderers = makeSysarchRenderers(respNames);
    const presentationalOnly =
      '<component alias="billing_ui">' +
      '<name>BillingUI</name>' +
      '<kind>presentational</kind>' +
      '<purpose>Lets users see billing state.</purpose>' +
      '<owned-invariants>' +
      '<invariant>rendered state matches backend</invariant>' +
      '<invariant>one edit session per user</invariant>' +
      '</owned-invariants>' +
      '<primary-operations>' +
      '<operation>render billing state</operation>' +
      '<operation>submit plan change</operation>' +
      '<operation>cancel edit</operation>' +
      '</primary-operations>' +
      '<responsibilities><resp id="resp_billing"/></responsibilities>' +
      '</component>';
    const xml = wrapInSysarch(presentationalOnly);
    render(<XmlDocument content={xml} renderers={renderers} />);
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/1 responsibility not assigned/);
    // Scope the name lookup to the warning panel — the
    // presentational component's own resp list renders its
    // (mirrored) resp names from the same map, so we can't use a
    // document-wide getByText here.
    expect(alert).toHaveTextContent('Billing');
    expect(alert).toHaveTextContent('(resp_billing)');
  });
});
