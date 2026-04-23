import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RequirementsListTab } from './RequirementsListTab';

describe('RequirementsListTab', () => {
  it('renders a hint when content is empty', () => {
    render(<RequirementsListTab content="" featureNames={{}} />);
    expect(screen.getByText(/No content yet/)).toBeInTheDocument();
  });

  it('extracts and renders the requirements subtree from a full draft', () => {
    const xml =
      '<introduction>Long intro paragraph the user does not want to scroll through.</introduction>' +
      '<requirements>' +
      '<responsibility>' +
      '<name>session-state lifecycle</name>' +
      '<feats><feat id="feat_login01"/></feats>' +
      '</responsibility>' +
      '<responsibility>' +
      '<name>invoice state transitions</name>' +
      '<feats><feat id="feat_billing"/></feats>' +
      '</responsibility>' +
      '</requirements>';
    render(
      <RequirementsListTab
        content={xml}
        featureNames={{ feat_login01: 'Login', feat_billing: 'Billing' }}
      />,
    );
    expect(screen.getByText('session-state lifecycle')).toBeInTheDocument();
    expect(screen.getByText('invoice state transitions')).toBeInTheDocument();
    // Introduction must not leak through.
    expect(screen.queryByText(/Long intro/)).not.toBeInTheDocument();
  });

  it('shows a hint when the draft has no <requirements> block', () => {
    render(
      <RequirementsListTab
        content="<introduction>intro only</introduction>"
        featureNames={{}}
      />,
    );
    expect(screen.getByText(/missing a/)).toBeInTheDocument();
  });
});
