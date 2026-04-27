import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { XmlDocument } from './XmlDocument';
import { makeComparchRenderers } from './comparchRenderers';

/**
 * The per-subcomponent ``<owns>`` block is the load-bearing new
 * shape post-Phase-A: it carries each subcomp's parent-resp
 * claims + per-resp feat slices. The renderer surfaces those
 * claims as readable rows, resolves resp + feat IDs to display
 * names from the project-level lookups, and handles the
 * multi-owner case (same resp under multiple subcomps) by
 * letting the duplication speak for itself in both Owns sections.
 */

const SUBCOMPONENT_HEAD = (alias: string, name: string) =>
  `<subcomponent alias="${alias}">` +
  `<name>${name}</name>` +
  `<purpose>${name} purpose.</purpose>` +
  '<owned-invariants>' +
  '<invariant>holds state</invariant>' +
  '<invariant>journaled</invariant>' +
  '</owned-invariants>' +
  '<primary-operations>' +
  '<operation>read</operation>' +
  '<operation>mutate</operation>' +
  '<operation>emit</operation>' +
  '</primary-operations>' +
  `<responsibilities>${name} prose body.</responsibilities>`;

const SUBCOMPONENT = (
  alias: string,
  name: string,
  ownsXml: string,
  foundation: boolean = false,
) =>
  SUBCOMPONENT_HEAD(alias, name) +
  ownsXml +
  (foundation ? '<foundation/>' : '') +
  '</subcomponent>';

const wrapInComparch = (subcomponentsXml: string, subDepsXml: string = '') =>
  '<comparch>' +
  '<technical-specification>Python.</technical-specification>' +
  '<public-surface>foo()</public-surface>' +
  '<private-surface>_bar()</private-surface>' +
  '<failure-surface>foo bug corrupts owned state.</failure-surface>' +
  '<policies></policies>' +
  '<dependencies></dependencies>' +
  `<subcomponents>${subcomponentsXml}</subcomponents>` +
  `<sub-dependencies>${subDepsXml}</sub-dependencies>` +
  '</comparch>';

describe('comparchRenderers Owns section', () => {
  it('renders each claimed resp + feat slice with names resolved from the lookups', () => {
    const xml = wrapInComparch(
      SUBCOMPONENT(
        'token_store',
        'TokenStore',
        '<owns><resp id="resp_payment01"><feat id="feat_card_v01"/></resp></owns>',
      ) + SUBCOMPONENT('foundation', 'Foundation', '<owns/>', true),
    );
    const renderers = makeComparchRenderers(
      { resp_payment01: 'Payment Collection' },
      { feat_card_v01: 'Card Capture' },
    );
    render(<XmlDocument content={xml} renderers={renderers} />);

    // The Owns label appears once per subcomp (TokenStore + Foundation).
    expect(screen.getAllByText('Owns').length).toBe(2);

    // TokenStore's claim renders the resp as ``Name (id)`` and the
    // feat as ``FeatName (feat_id)``.
    expect(
      screen.getByText('Payment Collection (resp_payment01)'),
    ).toBeInTheDocument();
    expect(screen.getByText('Card Capture (feat_card_v01)')).toBeInTheDocument();

    // Foundation has empty <owns/> → the no-claims sentinel renders.
    expect(
      screen.getByText(/No parent-responsibility claims/),
    ).toBeInTheDocument();
  });

  it('multi-owner: the same resp surfaces in both subcomps Owns sections', () => {
    // resp_payment01 split across CardInput (handles feat_card_v01)
    // and Lock Manager (handles feat_lock_init); each sub claims a
    // distinct feat slice. The renderer must show the resp under
    // both — no special multi-owner UI, just duplicated chips.
    const xml = wrapInComparch(
      SUBCOMPONENT(
        'card_input',
        'CardInput',
        '<owns><resp id="resp_payment01"><feat id="feat_card_v01"/></resp></owns>',
      ) +
        SUBCOMPONENT(
          'lock_manager',
          'LockManager',
          '<owns><resp id="resp_payment01"><feat id="feat_lock_init"/></resp></owns>',
        ) +
        SUBCOMPONENT('foundation', 'Foundation', '<owns/>', true),
    );
    const renderers = makeComparchRenderers(
      { resp_payment01: 'Payment Collection' },
      {
        feat_card_v01: 'Card Capture',
        feat_lock_init: 'Idempotency Lock',
      },
    );
    render(<XmlDocument content={xml} renderers={renderers} />);

    // resp_payment01 appears in both CardInput's and LockManager's
    // Owns sections — duplication IS the multi-owner affordance.
    const respMatches = screen.getAllByText('Payment Collection (resp_payment01)');
    expect(respMatches.length).toBe(2);

    // Each owner's per-resp feat slice is distinct.
    expect(screen.getByText('Card Capture (feat_card_v01)')).toBeInTheDocument();
    expect(
      screen.getByText('Idempotency Lock (feat_lock_init)'),
    ).toBeInTheDocument();
  });

  it('falls back to bare IDs when respNames / featureNames lookups are empty', () => {
    const xml = wrapInComparch(
      SUBCOMPONENT(
        'token_store',
        'TokenStore',
        '<owns><resp id="resp_payment01"><feat id="feat_card_v01"/></resp></owns>',
      ) + SUBCOMPONENT('foundation', 'Foundation', '<owns/>', true),
    );
    const renderers = makeComparchRenderers();
    render(<XmlDocument content={xml} renderers={renderers} />);
    // Bare resp_id (no parenthesised name) when the lookup misses.
    expect(screen.getByText('resp_payment01')).toBeInTheDocument();
    expect(screen.getByText('feat_card_v01')).toBeInTheDocument();
  });

  it('renders the whole-resp sentinel when an <owns><resp> has no <feat> children', () => {
    const xml = wrapInComparch(
      SUBCOMPONENT(
        'token_store',
        'TokenStore',
        '<owns><resp id="resp_payment01"/></owns>',
      ) + SUBCOMPONENT('foundation', 'Foundation', '<owns/>', true),
    );
    const renderers = makeComparchRenderers({ resp_payment01: 'Payment Collection' });
    render(<XmlDocument content={xml} renderers={renderers} />);
    expect(
      screen.getByText('Payment Collection (resp_payment01)'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/whole resp, no feat slice/),
    ).toBeInTheDocument();
  });

  it('renders the <responsibilities> prose alongside the structured Owns block', () => {
    const xml = wrapInComparch(
      SUBCOMPONENT(
        'token_store',
        'TokenStore',
        '<owns><resp id="resp_payment01"/></owns>',
      ) + SUBCOMPONENT('foundation', 'Foundation', '<owns/>', true),
    );
    const renderers = makeComparchRenderers({ resp_payment01: 'Payment Collection' });
    render(<XmlDocument content={xml} renderers={renderers} />);
    // Responsibilities section header + the seeded prose body.
    const sectionHeaders = screen.getAllByText('Responsibilities');
    expect(sectionHeaders.length).toBe(2);
    expect(screen.getByText('TokenStore prose body.')).toBeInTheDocument();
    expect(screen.getByText('Foundation prose body.')).toBeInTheDocument();
  });

  it('flags the foundation subcomponent with the foundation badge', () => {
    const xml = wrapInComparch(
      SUBCOMPONENT(
        'token_store',
        'TokenStore',
        '<owns><resp id="resp_payment01"/></owns>',
      ) + SUBCOMPONENT('foundation', 'Foundation', '<owns/>', true),
    );
    const renderers = makeComparchRenderers({ resp_payment01: 'Payment Collection' });
    render(<XmlDocument content={xml} renderers={renderers} />);
    const badges = screen.getAllByText('foundation');
    // The badge appears on the Foundation subcomp only — not on
    // TokenStore. Foundation also shows up as the subcomp's display
    // name, so the badge is the second match scoped via the title
    // attribute on the badge span.
    const badgeOnly = badges.filter((el) =>
      (el as HTMLElement).getAttribute('title')?.includes('Foundation subcomponent'),
    );
    expect(badgeOnly.length).toBe(1);
  });

  it('hides the un-fanned-out sentinel when at least one subcomponent is present', () => {
    const xml = wrapInComparch(
      SUBCOMPONENT(
        'token_store',
        'TokenStore',
        '<owns><resp id="resp_payment01"/></owns>',
      ) + SUBCOMPONENT('foundation', 'Foundation', '<owns/>', true),
    );
    const renderers = makeComparchRenderers({ resp_payment01: 'Payment Collection' });
    render(<XmlDocument content={xml} renderers={renderers} />);
    expect(screen.queryByText(/Un-fanned-out/)).not.toBeInTheDocument();
  });

  it('renders the un-fanned-out sentinel when <subcomponents> is empty', () => {
    const xml = wrapInComparch('');
    const renderers = makeComparchRenderers();
    render(<XmlDocument content={xml} renderers={renderers} />);
    expect(
      screen.getByText(/Un-fanned-out: this component does not decompose/),
    ).toBeInTheDocument();
  });
});

