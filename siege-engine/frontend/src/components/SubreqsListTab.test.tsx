import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SubreqsListTab } from './SubreqsListTab';

const PARENTS = [
  { id: 'resp_billing01', name: 'Billing Cycle' },
  { id: 'resp_invoice02', name: 'Invoice Emission' },
];

const TWO_SUBRESPS = (
  '<introduction>Two parents covered by two subresps.</introduction>' +
  '<subrequirements>' +
  '<subresponsibility>' +
  '<name>Tokenization</name>' +
  '<intent>Convert raw cards to tokens.</intent>' +
  '<derived-from><resp id="resp_billing01"/></derived-from>' +
  '</subresponsibility>' +
  '<subresponsibility>' +
  '<name>Delivery</name>' +
  '<intent>Send invoices to recipients.</intent>' +
  '<derived-from><resp id="resp_invoice02"/></derived-from>' +
  '</subresponsibility>' +
  '</subrequirements>'
);

describe('SubreqsListTab', () => {
  it('renders empty hint when content is missing', () => {
    render(<SubreqsListTab content="" parentResps={PARENTS} />);
    expect(
      screen.getByText(/No content yet — subresponsibilities will appear/),
    ).toBeInTheDocument();
  });

  it('renders missing-block hint when content lacks <subrequirements>', () => {
    render(
      <SubreqsListTab
        content="<introduction>only intro</introduction>"
        parentResps={PARENTS}
      />,
    );
    expect(
      screen.getByText(/missing a/),
    ).toBeInTheDocument();
  });

  it('renders subresps grouped under their parent resps', () => {
    render(<SubreqsListTab content={TWO_SUBRESPS} parentResps={PARENTS} />);
    // Both parent headers present.
    expect(screen.getByText('Billing Cycle')).toBeInTheDocument();
    expect(screen.getByText('Invoice Emission')).toBeInTheDocument();
    // Subresps land under their respective parents.
    expect(screen.getByText('Tokenization')).toBeInTheDocument();
    expect(screen.getByText('Delivery')).toBeInTheDocument();
    // Intent prose visible.
    expect(
      screen.getByText('Convert raw cards to tokens.'),
    ).toBeInTheDocument();
  });

  it('warns prominently when a parent has no covering subresp', () => {
    const parents = [
      ...PARENTS,
      { id: 'resp_orphan03', name: 'Orphan Parent' },
    ];
    render(<SubreqsListTab content={TWO_SUBRESPS} parentResps={parents} />);
    expect(
      screen.getByText(/No subresponsibilities derived from this parent/),
    ).toBeInTheDocument();
  });

  it('flags a multi-parent subresp as shared', () => {
    const sharedXml = (
      '<subrequirements>' +
      '<subresponsibility>' +
      '<name>Retry Scheduling</name>' +
      '<intent>Shared backoff across both parents.</intent>' +
      '<derived-from>' +
      '<resp id="resp_billing01"/>' +
      '<resp id="resp_invoice02"/>' +
      '</derived-from>' +
      '</subresponsibility>' +
      '</subrequirements>'
    );
    render(<SubreqsListTab content={sharedXml} parentResps={PARENTS} />);
    // The same subresp shows up under both parent headers — find
    // multiple matches.
    const occurrences = screen.getAllByText('Retry Scheduling');
    expect(occurrences.length).toBe(2);
    const sharedBadges = screen.getAllByText(/shared · 2 parents/);
    expect(sharedBadges.length).toBe(2);
  });

  it('surfaces orphan subresps when derived-from lists no known parent', () => {
    const orphanXml = (
      '<subrequirements>' +
      '<subresponsibility>' +
      '<name>Stray</name>' +
      '<intent>Refers to a resp not assigned to this comp.</intent>' +
      '<derived-from><resp id="resp_unknown01"/></derived-from>' +
      '</subresponsibility>' +
      '</subrequirements>'
    );
    render(<SubreqsListTab content={orphanXml} parentResps={PARENTS} />);
    expect(screen.getByText(/Orphaned subresps/)).toBeInTheDocument();
    expect(screen.getByText(/Stray/)).toBeInTheDocument();
  });
});
