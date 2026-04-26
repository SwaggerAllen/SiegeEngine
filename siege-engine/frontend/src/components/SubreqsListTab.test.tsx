import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SubreqsListTab } from './SubreqsListTab';

const PARENTS = [
  { id: 'resp_billing01', name: 'Billing Cycle' },
  { id: 'resp_invoice02', name: 'Invoice Emission' },
];

const FEATURE_NAMES: Record<string, string> = {
  feat_card01: 'Card Payments',
  feat_invoice02: 'Invoice Delivery',
};

const TWO_SUBRESPS = (
  '<introduction>Two parents covered by two subresps.</introduction>' +
  '<subrequirements>' +
  '<subresponsibility>' +
  '<name>Tokenization</name>' +
  '<feats><feat id="feat_card01"/></feats>' +
  '<derived-from><resp id="resp_billing01"/></derived-from>' +
  '</subresponsibility>' +
  '<subresponsibility>' +
  '<name>Delivery</name>' +
  '<feats><feat id="feat_invoice02"/></feats>' +
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
    render(
      <SubreqsListTab
        content={TWO_SUBRESPS}
        parentResps={PARENTS}
        featureNames={FEATURE_NAMES}
      />,
    );
    // Both parent headers present.
    expect(screen.getByText('Billing Cycle')).toBeInTheDocument();
    expect(screen.getByText('Invoice Emission')).toBeInTheDocument();
    // Subresps land under their respective parents.
    expect(screen.getByText('Tokenization')).toBeInTheDocument();
    expect(screen.getByText('Delivery')).toBeInTheDocument();
    // Feat-count pill is rendered (collapsed by default).
    const featPills = screen.getAllByRole('button', {
      name: /Show 1 feature tag/,
    });
    expect(featPills.length).toBe(2);
  });

  it('warns prominently when a parent has no covering subresp', () => {
    const parents = [
      ...PARENTS,
      { id: 'resp_orphan03', name: 'Orphan Parent' },
    ];
    render(
      <SubreqsListTab
        content={TWO_SUBRESPS}
        parentResps={parents}
        featureNames={FEATURE_NAMES}
      />,
    );
    expect(
      screen.getByText(/No subresponsibilities derived from this parent/),
    ).toBeInTheDocument();
  });

  it('resolves parent resp ids to names when expanded', () => {
    render(
      <SubreqsListTab
        content={TWO_SUBRESPS}
        parentResps={PARENTS}
        featureNames={FEATURE_NAMES}
      />,
    );
    // Find the parent-resp pill button and expand it.
    const parentButton = screen.getAllByRole('button', {
      name: /Show 1 parent responsibility/i,
    })[0];
    fireEvent.click(parentButton);
    // The resp id is rendered alongside the resolved name in the
    // expanded chip; the section header above already shows the
    // raw name, so disambiguate via the parens-formatted id.
    expect(screen.getByText('(resp_billing01)')).toBeInTheDocument();
  });

  it('flags a multi-parent subresp as shared', () => {
    const sharedXml = (
      '<subrequirements>' +
      '<subresponsibility>' +
      '<name>Retry Scheduling</name>' +
      '<feats><feat id="feat_card01"/><feat id="feat_invoice02"/></feats>' +
      '<derived-from>' +
      '<resp id="resp_billing01"/>' +
      '<resp id="resp_invoice02"/>' +
      '</derived-from>' +
      '</subresponsibility>' +
      '</subrequirements>'
    );
    render(
      <SubreqsListTab
        content={sharedXml}
        parentResps={PARENTS}
        featureNames={FEATURE_NAMES}
      />,
    );
    // The same subresp shows up under both parent headers — find
    // multiple matches.
    const occurrences = screen.getAllByText('Retry Scheduling');
    expect(occurrences.length).toBe(2);
    const sharedBadges = screen.getAllByText(/shared · 2 parents/);
    expect(sharedBadges.length).toBe(2);
  });

  it('renders empty <feats/> as a card with no feat pill', () => {
    // Component-emergent atom — empty feats block is legal.
    const emptyFeatsXml = (
      '<subrequirements>' +
      '<subresponsibility>' +
      '<name>Token Cache Eviction</name>' +
      '<feats/>' +
      '<derived-from><resp id="resp_billing01"/></derived-from>' +
      '</subresponsibility>' +
      '</subrequirements>'
    );
    render(
      <SubreqsListTab
        content={emptyFeatsXml}
        parentResps={PARENTS}
        featureNames={FEATURE_NAMES}
      />,
    );
    expect(screen.getByText('Token Cache Eviction')).toBeInTheDocument();
    // No feat-count pill rendered for an empty feats list.
    expect(
      screen.queryByRole('button', { name: /feature tag/i }),
    ).not.toBeInTheDocument();
  });

  it('surfaces orphan subresps when derived-from lists no known parent', () => {
    const orphanXml = (
      '<subrequirements>' +
      '<subresponsibility>' +
      '<name>Stray</name>' +
      '<feats><feat id="feat_card01"/></feats>' +
      '<derived-from><resp id="resp_unknown01"/></derived-from>' +
      '</subresponsibility>' +
      '</subrequirements>'
    );
    render(
      <SubreqsListTab
        content={orphanXml}
        parentResps={PARENTS}
        featureNames={FEATURE_NAMES}
      />,
    );
    expect(screen.getByText(/Orphaned subresps/)).toBeInTheDocument();
    expect(screen.getByText(/Stray/)).toBeInTheDocument();
  });
});
