import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { FeatureListTab } from './FeatureListTab';

describe('FeatureListTab', () => {
  it('renders an empty-state hint when content is empty', () => {
    render(<FeatureListTab content="" />);
    expect(screen.getByText(/No content yet/)).toBeInTheDocument();
  });

  it('extracts and renders the features subtree from a full draft', () => {
    const xml =
      '<introduction>Long intro paragraph the user does not want to scroll through.</introduction>' +
      '<features>' +
      '<feature><name>Billing</name><intent>Users pay for plans.</intent></feature>' +
      '<feature><name>Onboarding</name><intent>New customers complete setup.</intent></feature>' +
      '</features>' +
      '<vocabulary></vocabulary>';
    render(<FeatureListTab content={xml} />);
    // Both features land — the introduction paragraph does NOT.
    expect(screen.getByText('Billing')).toBeInTheDocument();
    expect(screen.getByText('Onboarding')).toBeInTheDocument();
    expect(screen.queryByText(/Long intro/)).not.toBeInTheDocument();
  });

  it('shows a hint when the draft has no <features> block', () => {
    render(<FeatureListTab content="<introduction>only intro</introduction>" />);
    expect(screen.getByText(/missing a/)).toBeInTheDocument();
  });
});
